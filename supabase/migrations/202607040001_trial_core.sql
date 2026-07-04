-- Durable trial grant, signed ledger, and remediation lifecycle schema.

alter table public.uploaded_files
    add column page_count integer null,
    add constraint uq_uploaded_files_id_owner_id
        unique (id, owner_id),
    add constraint ck_uploaded_files_page_count_nonnegative
        check (page_count is null or page_count >= 0);

-- The legacy SQLAlchemy FK was created without ON DELETE CASCADE and its name
-- varies by deployment. Replace every owner_id -> users FK deterministically.
do $$
declare
    owner_fk record;
begin
    for owner_fk in
        select constraint_row.conname
        from pg_catalog.pg_constraint as constraint_row
        where constraint_row.contype = 'f'
          and constraint_row.conrelid = 'public.uploaded_files'::regclass
          and constraint_row.confrelid = 'public.users'::regclass
          and (
              select column_row.attnum
              from pg_catalog.pg_attribute as column_row
              where column_row.attrelid = constraint_row.conrelid
                and column_row.attname = 'owner_id'
          ) = any (constraint_row.conkey)
    loop
        execute format(
            'alter table public.uploaded_files drop constraint %I',
            owner_fk.conname
        );
    end loop;
end;
$$;

alter table public.uploaded_files
    add constraint fk_uploaded_files_owner_id_users
        foreign key (owner_id) references public.users(id) on delete cascade;

create function public.prevent_uploaded_file_owner_update()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    if new.owner_id is distinct from old.owner_id then
        raise exception 'uploaded file owner is immutable';
    end if;
    return new;
end;
$$;

create trigger uploaded_files_immutable_owner
before update of owner_id on public.uploaded_files
for each row execute function public.prevent_uploaded_file_owner_update();

create table public.trial_accounts (
    user_id text primary key references public.users(id) on delete cascade,
    normalized_email text not null,
    normalized_domain text not null,
    granted_pages integer not null,
    eligibility_rule_version text not null,
    created_at timestamp with time zone not null default now(),
    constraint ck_trial_accounts_granted_pages_nonnegative
        check (granted_pages >= 0),
    constraint ck_trial_accounts_normalized_email
        check (normalized_email = lower(trim(normalized_email))),
    constraint ck_trial_accounts_normalized_domain
        check (normalized_domain = lower(trim(normalized_domain)))
);

create table public.remediation_jobs (
    id text primary key,
    user_id text not null references public.users(id) on delete cascade,
    file_id text null references public.uploaded_files(id) on delete set null,
    report_id text null references public.accessibility_reports(id) on delete set null,
    status text not null,
    page_count integer not null,
    idempotency_key text not null,
    failure_reason text null,
    output_artifact_key text null,
    report_artifact_key text null,
    response_json text null,
    processing_started_at timestamp with time zone null,
    lease_expires_at timestamp with time zone null,
    created_at timestamp with time zone not null default now(),
    updated_at timestamp with time zone not null default now(),
    completed_at timestamp with time zone null,
    constraint uq_remediation_jobs_user_idempotency
        unique (user_id, idempotency_key),
    constraint uq_remediation_jobs_id_user_id
        unique (id, user_id),
    constraint ck_remediation_jobs_status
        check (status in ('pending', 'reserved', 'processing', 'succeeded', 'failed', 'released')),
    constraint ck_remediation_jobs_page_count_nonnegative
        check (page_count >= 0)
);

create index ix_remediation_jobs_file_id
    on public.remediation_jobs (file_id);
create index ix_remediation_jobs_report_id
    on public.remediation_jobs (report_id);
create index ix_remediation_jobs_status
    on public.remediation_jobs (status);

create table public.trial_ledger_entries (
    id text primary key,
    user_id text not null references public.users(id) on delete cascade,
    job_id text null,
    entry_type text not null,
    granted_delta integer not null default 0,
    reserved_delta integer not null default 0,
    consumed_delta integer not null default 0,
    idempotency_key text not null,
    created_at timestamp with time zone not null default now(),
    constraint uq_trial_ledger_user_idempotency
        unique (user_id, idempotency_key),
    constraint fk_trial_ledger_job_owner
        foreign key (job_id, user_id)
        references public.remediation_jobs(id, user_id),
    constraint ck_trial_ledger_entry_type
        check (entry_type in ('grant', 'reserve', 'consume', 'release')),
    constraint ck_trial_ledger_signed_deltas
        check (
            (entry_type = 'grant'
                and granted_delta > 0
                and reserved_delta = 0
                and consumed_delta = 0
                and job_id is null)
            or (entry_type = 'reserve'
                and granted_delta = 0
                and reserved_delta > 0
                and consumed_delta = 0
                and job_id is not null)
            or (entry_type = 'release'
                and granted_delta = 0
                and reserved_delta < 0
                and consumed_delta = 0
                and job_id is not null)
            or (entry_type = 'consume'
                and granted_delta = 0
                and reserved_delta < 0
                and consumed_delta > 0
                and consumed_delta = -reserved_delta
                and job_id is not null)
        )
);

create index ix_trial_ledger_entries_job_id
    on public.trial_ledger_entries (job_id);

create function public.prevent_trial_grant_provenance_update()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    if new.user_id is distinct from old.user_id
       or new.normalized_email is distinct from old.normalized_email
       or new.normalized_domain is distinct from old.normalized_domain
       or new.granted_pages is distinct from old.granted_pages
       or new.eligibility_rule_version is distinct from old.eligibility_rule_version
       or new.created_at is distinct from old.created_at then
        raise exception 'trial account eligibility provenance is immutable';
    end if;
    return new;
end;
$$;

create trigger trial_accounts_immutable_grant_provenance
before update on public.trial_accounts
for each row execute function public.prevent_trial_grant_provenance_update();

create function public.enforce_remediation_job_file_ownership()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    if new.file_id is not null
       and not exists (
           select 1
           from public.uploaded_files as uploaded_file
           where uploaded_file.id = new.file_id
             and uploaded_file.owner_id = new.user_id
       ) then
        raise exception 'remediation job file must be owned by the job user'
            using errcode = '23503';
    end if;
    return new;
end;
$$;

create trigger remediation_jobs_enforce_file_ownership
before insert or update of file_id, user_id on public.remediation_jobs
for each row execute function public.enforce_remediation_job_file_ownership();

create function public.prevent_trial_ledger_mutation()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    if tg_op = 'DELETE' then
        if exists (
            select 1 from public.users where id = old.user_id
        ) then
            raise exception 'trial ledger entries are append-only';
        end if;
        return old;
    end if;

    raise exception 'trial ledger entries are append-only';
end;
$$;

create trigger trial_ledger_entries_append_only
before update or delete on public.trial_ledger_entries
for each row execute function public.prevent_trial_ledger_mutation();

create function public.set_remediation_job_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create trigger remediation_jobs_set_updated_at
before update on public.remediation_jobs
for each row execute function public.set_remediation_job_updated_at();

alter table public.trial_accounts enable row level security;
alter table public.trial_ledger_entries enable row level security;
alter table public.remediation_jobs enable row level security;

create policy "Users can view their own trial account"
on public.trial_accounts
for select
to authenticated
using (auth.uid()::text = user_id);

create policy "Users can view their own trial ledger entries"
on public.trial_ledger_entries
for select
to authenticated
using (auth.uid()::text = user_id);

create policy "Users can view their own remediation jobs"
on public.remediation_jobs
for select
to authenticated
using (auth.uid()::text = user_id);
