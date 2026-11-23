from pathlib import Path

from PyInstaller.utils.hooks import get_package_paths

# AutoTokenizer resolves Qwen2 and Llama through these aliases in Transformers 5.21.
tokenizer_families = {"auto", "audioflamingo3", "encoder_decoder", "idefics", "llama", "qwen2"}
_, models_dir = get_package_paths("transformers.models")
excludedimports = [
    f"transformers.models.{path.name}"
    for path in Path(models_dir).iterdir()
    if (path / "__init__.py").is_file() and path.name not in tokenizer_families
]
hiddenimports = [
    "transformers.models.auto.tokenization_auto",
    "transformers.models.llama.tokenization_llama",
    "transformers.models.qwen2.tokenization_qwen2",
]
