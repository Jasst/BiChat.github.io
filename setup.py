from cx_Freeze import setup, Executable

build_exe_options = {
    "packages": ["flask", "mnemonic", "cryptography.fernet"],
    "include_files": ["templates/", "static/"]
}

setup(
    name="BlockchainMessenger",
    version="1.0",
    description="A blockchain-based messaging application",
    options={"build_exe": build_exe_options},
    executables=[Executable("app.py")]
)
