def test_public_provenance_matches_identity_and_suppression_guards(client):
    data = client.get('/api/methods').json()
    provenance = data['provenance']
    limits = ' '.join(provenance['known_limits'])
    assert 'Cells under 12 claims are suppressed' not in limits
    assert 'Missing servicing identity does not erase billing totals' in limits
    assert provenance['all_data_public'] is False
    assert 'private operational records' in provenance['public_data_note']
    assert 'thresholds or predictive accuracy' in data['composite_methodology']
    explanations = ' '.join(row['explanation'] for row in data['signals'])
    assert 'single strongest predictor' not in explanations
    assert 'match alone does not establish' in explanations
