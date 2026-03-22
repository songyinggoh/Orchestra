import pytest
from wasmtime import Config, Engine, Linker, Module, Store


def test_wasm_filesystem_isolation_trap():
    """
    Verify that a Wasm module without WASI pre-opens cannot access the host filesystem.
    This is a core P0 security requirement for Phase 4.
    """
    config = Config()
    engine = Engine(config)
    store = Store(engine)

    # A minimal WebAssembly module (WAT) that tries to call an unimported function or
    # would normally need WASI to touch the filesystem.
    # In this test, we verify that because we DON'T link WASI, it has no way to touch the host.
    wat = """
    (module
      (func (export "run")
        (nop)
      )
    )
    """
    module = Module(engine, wat)
    linker = Linker(engine)
    # We do NOT call linker.define_wasi() here.

    instance = linker.instantiate(store, module)
    run = instance.exports(store)["run"]

    # This should succeed because it does nothing.
    run(store)

    # In a real smoke test, we'd use a module compiled to try and open a file.
    # If it's not linked to WASI, it won't even have the 'fd_open' import and
    # will fail at instantiation.
    wat_bad = """
    (module
      (import "wasi_snapshot_preview1" "path_open"
        (func $path_open
          (param i32 i32 i32 i32 i32 i64 i64 i32 i32) (result i32)))
      (func (export "try_open")
        (call $path_open
          (i32.const 0) (i32.const 0) (i32.const 0) (i32.const 0)
          (i32.const 0) (i64.const 0) (i64.const 0) (i32.const 0) (i32.const 0))
        drop
      )
    )
    """
    module_bad = Module(engine, wat_bad)
    linker_bad = Linker(engine)

    # This MUST fail because we didn't define WASI imports
    with pytest.raises(Exception) as excinfo:
        linker_bad.instantiate(store, module_bad)

    assert "unknown import" in str(excinfo.value).lower()
    assert "wasi_snapshot_preview1" in str(excinfo.value)
