from PyInstaller.utils.hooks import collect_all, is_module_or_submodule

datas, binaries, hiddenimports = collect_all(
    "chromadb",
    include_py_files=False,
    exclude_datas=["test/**"],
    filter_submodules=lambda name: not is_module_or_submodule(name, "chromadb.test"),
)
