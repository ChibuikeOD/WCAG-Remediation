"""Public settings and subprocess methods, without environment integrations."""
import ast
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pytest
from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings


def budget_settings():
    source=Path(__file__).parents[1]/'config.py';tree=ast.parse(source.read_text(encoding='utf-8-sig'))
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Settings')
    fields=[n for n in cls.body if isinstance(n,ast.AnnAssign) and n.target.id in ('OPENDATALOADER_TIMEOUT_SECONDS','PDF_SUBPROCESS_TIMEOUT_SECONDS')]
    public=ast.ClassDef(name='PublicBudget',bases=[ast.Name(id='BaseSettings',ctx=ast.Load())],keywords=[],body=fields,decorator_list=[])
    namespace=dict(BaseSettings=BaseSettings,Field=Field)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[public],type_ignores=[])),str(source),'exec'),namespace)
    return namespace['PublicBudget']


def methods():
    source=Path(__file__).parents[1]/'opendataloader_layout.py';tree=ast.parse(source.read_text())
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and any(isinstance(m,ast.FunctionDef) and m.name=='_run_installed_package' for m in n.body))
    body=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in ('_run_local_jar','_run_installed_package')]
    public=ast.ClassDef(name='Runner',bases=[],keywords=[],body=body,decorator_list=[])
    namespace=dict(__package__='backend',Path=Path,Optional=Optional,RuntimeResolution=object,subprocess=subprocess)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[public],type_ignores=[])),str(source),'exec'),namespace)
    return namespace['Runner']()


@pytest.mark.parametrize('value',[0,-1,901])
def test_layout_budget_has_explicit_lower_and_upper_bounds(value):
    with pytest.raises(ValidationError):budget_settings()(OPENDATALOADER_TIMEOUT_SECONDS=value,_env_file=None)


def test_layout_budget_is_independent_and_configurable_from_public_env(monkeypatch):
    monkeypatch.setenv('OPENDATALOADER_TIMEOUT_SECONDS','360')
    settings=budget_settings()(_env_file=None)
    assert settings.OPENDATALOADER_TIMEOUT_SECONDS==360 and settings.PDF_SUBPROCESS_TIMEOUT_SECONDS==180


@pytest.mark.parametrize('local',[False,True])
def test_each_jar_route_has_the_same_hard_layout_deadline(monkeypatch,local):
    monkeypatch.setitem(sys.modules,'backend.config',SimpleNamespace(settings=SimpleNamespace(OPENDATALOADER_TIMEOUT_SECONDS=360,PDF_SUBPROCESS_TIMEOUT_SECONDS=180)))
    calls=[]
    monkeypatch.setattr(subprocess,'run',lambda *a,**kw:calls.append((a,kw)))
    runner=methods();runner._locate_bundled_jar=lambda:Path('pinned.jar')
    if local:runner._run_local_jar(Path('input.pdf'),Path('owned-output'),SimpleNamespace(jar_path=Path('pinned.jar')))
    else:runner._run_installed_package(Path('input.pdf'),Path('owned-output'))
    assert calls[0][1]['timeout']==360 and calls[0][1]['check'] is True


def test_timeout_reports_measurement_without_guessing_memory_cause(monkeypatch):
    monkeypatch.setitem(sys.modules,'backend.config',SimpleNamespace(settings=SimpleNamespace(OPENDATALOADER_TIMEOUT_SECONDS=180)))
    def timeout(command,**kwargs):raise subprocess.TimeoutExpired(command,kwargs['timeout'])
    monkeypatch.setattr(subprocess,'run',timeout)
    runner=methods();runner._locate_bundled_jar=lambda:Path('pinned.jar')
    with pytest.raises(RuntimeError,match='timed out after 180s') as caught:
        runner._run_installed_package(Path('input.pdf'),Path('owned-output'))
    assert isinstance(caught.value.__cause__,subprocess.TimeoutExpired)
    assert 'memory' not in str(caught.value).lower()


def test_missing_jar_never_falls_back_to_conversion_without_a_deadline(monkeypatch):
    monkeypatch.setitem(sys.modules,'backend.config',SimpleNamespace(settings=SimpleNamespace(OPENDATALOADER_TIMEOUT_SECONDS=180)))
    runner=methods();runner._locate_bundled_jar=lambda:None
    def reject(*args,**kwargs):raise AssertionError('unexpected subprocess')
    monkeypatch.setattr(subprocess,'run',reject)
    with pytest.raises(RuntimeError,match='bounded layout extraction unavailable'):
        runner._run_installed_package(Path('input.pdf'),Path('owned-output'))
