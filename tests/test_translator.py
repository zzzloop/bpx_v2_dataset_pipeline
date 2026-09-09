import io
import json
import pathlib
from unittest import mock

from bpx_v2_dataset_pipeline.collector.translator import TaskTranslator, _read_project_key


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def test_project_key_loader_reads_only_named_local_file(tmp_path: pathlib.Path) -> None:
    (tmp_path / ".env.local").write_text("OTHER=x\nDEEPSEEK_API_KEY=local-secret\n", encoding="utf-8")
    assert _read_project_key(tmp_path) == "local-secret"


def test_deepseek_request_is_stateless_small_and_current_only() -> None:
    translator = TaskTranslator("test-key")
    response = _Response(
        json.dumps({"choices": [{"message": {"content": '{"english":"Arrange the laboratory tools."}'}}]}).encode()
    )
    with mock.patch("urllib.request.urlopen", return_value=response) as urlopen:
        result = translator.translate("把实验器材整理好")

    request = urlopen.call_args.args[0]
    payload = json.loads(request.data)
    assert payload["model"] == "deepseek-v4-flash"
    assert payload["max_tokens"] == 128
    assert payload["thinking"] == {"type": "disabled"}
    assert len(payload["messages"]) == 2
    assert payload["messages"][1] == {"role": "user", "content": "把实验器材整理好"}
    assert result.english == "Arrange the laboratory tools."
    assert result.source == "deepseek_v4_flash"


def test_catalog_translation_does_not_spend_an_api_request() -> None:
    translator = TaskTranslator("test-key")
    with mock.patch("urllib.request.urlopen") as urlopen:
        result = translator.translate("抓取红色方块并放入桶中。")
    urlopen.assert_not_called()
    assert result.source == "preset"
