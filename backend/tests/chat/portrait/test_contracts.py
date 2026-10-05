import pytest

from magi.chat.portrait.contracts import TopicResult


@pytest.mark.parametrize(
    "topic,entities,empty",
    [
        ("", [], True),
        ("   ", [], True),
        ("topic", [], False),
        ("", ["entity"], False),
        (" ", ["entity"], False),
    ],
)
def test_topic_emptiness_requires_no_text_and_no_entities(topic, entities, empty):
    assert TopicResult(topic=topic, entities=entities).is_empty() is empty
