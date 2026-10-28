import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from core.persistence_middleware import PersistenceAcknowledgementMiddleware


@pytest.mark.parametrize('name', ['saved_search', 'notification'])
@pytest.mark.parametrize('state,status', [('synced', 200), ('conflict', 503), ('pending', 202)])
def test_store_mutations_acknowledge_cloud_state(tmp_path, monkeypatch, name, state, status):
    from core import saved_search_store, notification_store, gcs_sync
    saved = name == 'saved_search'
    store = saved_search_store if saved else notification_store
    filename = 'saved_searches.json' if saved else 'notifications.json'
    monkeypatch.setattr(store, '_SAVED_SEARCHES_FILE' if saved else '_NOTIFICATIONS_FILE', tmp_path / filename)
    monkeypatch.setattr(store, '_saved_searches' if saved else '_notifications', [])
    uploaded = []
    def upload(path):
        uploaded.append(path)
        gcs_sync._set_status(path, state)
        return state == 'synced'
    monkeypatch.setattr(gcs_sync, 'upload_file', upload)
    app = FastAPI()
    app.add_middleware(PersistenceAcknowledgementMiddleware)
    @app.post('/write')
    def write():
        return (store.create_saved_search('synthetic fixture', {'state': 'WI'}) if saved else
                store.add_notification('system', 'synthetic fixture', 'durability test'))
    with TestClient(app) as client:
        response = client.post('/write')
    assert response.status_code == status
    assert response.headers['x-mfi-persistence'] == {'synced': 'durable', 'conflict': 'failed', 'pending': 'pending'}[state]
    assert uploaded == [filename]
    assert (tmp_path / filename).is_file()
    monkeypatch.setattr(store, '_saved_searches' if saved else '_notifications', [])
    (store.load_saved_searches_from_disk if saved else store.load_notifications_from_disk)()
    assert len(store.list_saved_searches() if saved else store.list_notifications()) == 1


def test_local_write_failure_cannot_claim_success(tmp_path, monkeypatch):
    from core import saved_search_store as store
    monkeypatch.setattr(store, '_SAVED_SEARCHES_FILE', tmp_path / 'saved_searches.json')
    monkeypatch.setattr(store, '_saved_searches', [])
    def fail(*args, **kwargs):
        raise OSError('synthetic disk failure')
    monkeypatch.setattr(store, 'atomic_write_json', fail)
    app = FastAPI()
    app.add_middleware(PersistenceAcknowledgementMiddleware)
    @app.post('/write')
    def write():
        return store.create_saved_search('synthetic fixture', {})
    with TestClient(app) as client:
        response = client.post('/write')
    assert response.status_code == 503
    assert response.json()['changes_may_exist_locally'] is True
