from scripts.run_v19_raw_text_campaign import run


def test_v19_raw_text_campaign_has_no_false_pass_or_false_block():
    result = run(25)
    assert result["verdict"] == "PASS"
    assert result["total_cases"] == 100
    assert result["false_pass"] == 0
    assert result["false_block"] == 0
