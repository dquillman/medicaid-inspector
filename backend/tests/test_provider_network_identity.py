def test_billing_network_rejects_unusable_identities(client, auth_headers):
    response = client.get('/api/providers/0000000000/billing-network', headers=auth_headers)
    assert response.status_code == 422


def test_billing_network_does_not_enrich_invalid_connections(client, auth_headers, monkeypatch):
    from routes import providers
    async def query(sql, *args):
        return [{'connected_npi': 'UNKNOWN', 'relationship': 'servicing', 'total_paid': 50},
                {'connected_npi': '1234567885', 'relationship': 'billing', 'total_paid': 10}]
    monkeypatch.setattr(providers, 'query_async', query)
    response = client.get('/api/providers/1234567893/billing-network', headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body['total_connections'] == 2
    assert all(row['npi'] == '1234567885' for row in body['connections'])
    assert body['servicing_count'] == 1 and body['billing_count'] == 1

