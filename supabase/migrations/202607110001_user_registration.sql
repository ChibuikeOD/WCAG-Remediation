create table public.user_registration_profiles (
    user_id uuid primary key references auth.users(id) on delete cascade,
    full_name text not null,
    registering_for_institution boolean not null default false,
    institution_name text null,
    role_title text null,
    intended_use text null,
    registration_completed_at timestamp with time zone not null default now(),
    welcome_completed_at timestamp with time zone null,
    updated_at timestamp with time zone not null default now(),
    constraint ck_user_registration_full_name check (length(trim(full_name)) between 1 and 120),
    constraint ck_user_registration_institution check (
        not registering_for_institution
        or length(trim(coalesce(institution_name, ''))) > 0
    )
);

alter table public.user_registration_profiles enable row level security;
grant select, insert, update on public.user_registration_profiles to authenticated;

create policy "Users can view their own registration profile"
on public.user_registration_profiles for select to authenticated
using ((select auth.uid()) = user_id);

create policy "Users can create their own registration profile"
on public.user_registration_profiles for insert to authenticated
with check ((select auth.uid()) = user_id);

create policy "Users can update their own registration profile"
on public.user_registration_profiles for update to authenticated
using ((select auth.uid()) = user_id)
with check ((select auth.uid()) = user_id);

create function public.set_user_registration_updated_at()
returns trigger language plpgsql set search_path = '' as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create trigger user_registration_profiles_set_updated_at
before update on public.user_registration_profiles
for each row execute function public.set_user_registration_updated_at();
