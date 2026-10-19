import pytest


@pytest.fixture(autouse=True)
def _isolate_position_audit(tmp_path, monkeypatch):
    """20.10: файл общей сверки позиции (loop.AUDIT_FILE) вычисляется от живого state/ при импорте — тесты Runner
    не должны ни читать, ни писать живой файл."""
    from services.weex_grid import loop
    monkeypatch.setattr(loop, "AUDIT_FILE", tmp_path / "weex_position_audit.json", raising=False)
