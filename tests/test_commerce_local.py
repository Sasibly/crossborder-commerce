import importlib.util
import json
from pathlib import Path
import pytest


@pytest.fixture
def local_tool():
    path=Path(__file__).resolve().parents[1]/'scripts/commerce_local.py'
    spec=importlib.util.spec_from_file_location('commerce_local_tool',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_only_loopback_bindings_can_be_used_for_local_mutating_checks(local_tool):
    assert local_tool.loopback_url({'8000/tcp':[{'HostIp':'127.0.0.1','HostPort':'8031'}]})=='http://127.0.0.1:8031'
    assert local_tool.loopback_url({'8000/tcp':[{'HostIp':'::1','HostPort':'8031'}]})=='http://[::1]:8031'
    for ports in ({'8000/tcp':[{'HostIp':'0.0.0.0','HostPort':'8031'}]},
                  {'8000/tcp':[{'HostIp':'::','HostPort':'8031'}]},
                  {'8000/tcp':None},
                  {'8000/tcp':[{'HostIp':'127.0.0.1','HostPort':'8031'}],'9000/tcp':[{'HostIp':'0.0.0.0','HostPort':'9000'}]}):
        with pytest.raises(ValueError):local_tool.loopback_url(ports)


def test_private_review_config_prepared_without_overwriting_credentials(local_tool,tmp_path,monkeypatch):
    monkeypatch.setattr(local_tool,'ROOT',tmp_path)
    template=tmp_path/'.env.review-analysis.example';template.write_text('REVIEW_LLM_API_KEY=\n',encoding='utf-8')
    local_tool.prepare_review_config()
    private=tmp_path/'.env.review-analysis';assert private.read_text(encoding='utf-8')==template.read_text(encoding='utf-8')
    private.write_text('REVIEW_LLM_API_KEY=fake-private-key\n',encoding='utf-8')
    local_tool.prepare_review_config();assert 'fake-private-key' in private.read_text(encoding='utf-8')


def test_repeated_report_saves_preserve_old_result(local_tool,tmp_path):
    first=local_tool.save_report({'status':'passed','marker':'first'},tmp_path)
    second=local_tool.save_report({'status':'passed','marker':'second'},tmp_path)
    assert first!=second
    assert json.loads(Path(first).read_text(encoding='utf-8'))['marker']=='first'


def test_missing_reported_container_fails_without_guessing_existing_service(local_tool,monkeypatch):
    monkeypatch.setattr(local_tool,'compose',lambda *args,**kwargs:'')
    with pytest.raises(RuntimeError,match='未运行'):local_tool.inspect()


def test_startup_config_rejects_public_ports_before_creating_services(local_tool):
    config={'services':{'app':{'ports':[{'host_ip':'127.0.0.1','target':8000,'published':'8031','protocol':'tcp'}]}}}
    assert local_tool.validate_config(config)=='http://127.0.0.1:8031'
    for service in ({'network_mode':'host'},{'ports':[{'target':9000,'published':'9000'}]}):
        config['services']['other']=service
        with pytest.raises(ValueError):local_tool.validate_config(config)
