from triagedesk.auto_categories import fallback


def test_source_labels_and_text_rules_are_distinguished():
    assert fallback("Export", "", ["bug"])["method"] == "source_label"
    assert fallback("Please add PDF export", "", [])["category"] == "enhancement"
    assert fallback("How do I configure this?", "", [])["category"] == "question"
    assert fallback("The app crashes", "", [])["category"] == "bug"
    assert fallback("General discussion", "Nothing specific", []) is None
    assert fallback("General discussion", "Nothing specific", ["bug", "question"]) is None
    assert fallback("General discussion", "Nothing specific", ["help wanted"]) is None
