# Generate Rust dependencies of Python cryptography

Why?: Because, in Flathub sandbox, -share-network option is not allowed.

1. Get and uncompress Python cryptography sources somewhere.

2. Generate Cargo.lock file:

```bash
cd /path/to/cryptography-x.y.z
cargo vendor --manifest-path src/rust/Cargo.toml
```

3. Generate sources list JSON file in Komikku flatpak folder:

```bash
cd /path/to/Komikku/flatpak
python flatpak-cargo-generator.py /path/to/cryptography-x.y.z/src/rust/Cargo.lock -o python3-cryptography-cargo-deps.json
```

`python3-cryptography-cargo-deps.json` is used in `python3-keyring.json`.
