import pytest
from scripts.secure_operational_storage import remove_public_viewer


def test_private_principals_roles_and_conditions_survive_public_removal():
    bindings = [
        {'role': 'roles/storage.objectViewer', 'members': {'allUsers', 'serviceAccount:fixture'}},
        {'role': 'roles/storage.objectAdmin', 'members': {'serviceAccount:runtime'}},
        {'role': 'roles/storage.objectViewer', 'members': {'group:private'}, 'condition': {'expression': 'true'}},
    ]
    result = remove_public_viewer(bindings)
    assert result[0]['members'] == {'serviceAccount:fixture'}
    assert result[1:] == bindings[1:]
    assert 'allUsers' in bindings[0]['members']


def test_empty_public_binding_removed_and_unexpected_grants_stop_reconciliation():
    assert remove_public_viewer([{'role': 'roles/storage.objectViewer', 'members': {'allUsers'}}]) == []
    with pytest.raises(ValueError):
        remove_public_viewer([{'role': 'roles/storage.objectAdmin', 'members': {'allUsers'}}])
