#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import importlib
import inspect
import json
from pathlib import Path
import sys
import tempfile
import types


class Raises(contextlib.AbstractContextManager):
    def __init__(self, exception):
        self.exception = exception

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is None:
            raise AssertionError(f"did not raise {self.exception}")
        return bool(issubclass(exc_type, self.exception))


class Mark:
    def parametrize(self, names, values):
        names = tuple(item.strip() for item in names.split(","))
        values = tuple(values)

        def decorate(function):
            function.__robot_parametrize__ = (names, values)
            return function

        return decorate


pytest_stub = types.ModuleType("pytest")
pytest_stub.raises = Raises
pytest_stub.mark = Mark()


def cases(function):
    parameterization = getattr(function, "__robot_parametrize__", None)
    if parameterization is None:
        yield {}
        return
    names, values = parameterization
    for value in values:
        row = value if len(names) > 1 else (value,)
        yield dict(zip(names, row))


def selected_test_files(root: Path, requested: tuple[str, ...]):
    if not requested:
        return tuple(sorted(root.glob("test_*.py")))
    paths = []
    for name in requested:
        path = root / name
        if path.parent != root or not path.name.startswith("test_") or path.suffix != ".py" or not path.is_file():
            raise RuntimeError(f"TEST_MODULE_INVALID:{name}")
        paths.append(path)
    return tuple(paths)


def execute(root: Path, requested: tuple[str, ...] = ()) -> dict:
    sys.path.insert(0, str(root))
    passed = 0
    failures = []
    previous_pytest = sys.modules.get("pytest")
    sys.modules["pytest"] = pytest_stub
    try:
        for path in selected_test_files(root, requested):
            module = importlib.import_module(path.stem)
            for name, function in sorted(vars(module).items()):
                if not name.startswith("test_") or not callable(function) or function.__module__ != module.__name__:
                    continue
                for index, provided in enumerate(cases(function)):
                    with tempfile.TemporaryDirectory(prefix="zoran-source-test-") as tmp:
                        arguments = dict(provided)
                        unsupported = []
                        for parameter in inspect.signature(function).parameters:
                            if parameter == "tmp_path":
                                arguments[parameter] = Path(tmp)
                            elif parameter not in arguments:
                                unsupported.append(parameter)
                        if unsupported:
                            failures.append([path.name, name, index, f"unsupported fixtures:{unsupported}"])
                            continue
                        try:
                            function(**arguments)
                            passed += 1
                        except Exception as exc:
                            failures.append([path.name, name, index, repr(exc)])
    finally:
        if previous_pytest is None:
            sys.modules.pop("pytest", None)
        else:
            sys.modules["pytest"] = previous_pytest
    return {"runner": "zoran-bundled-source-only-v1", "passed": passed, "failed": len(failures), "failures": failures}


def main() -> None:
    root = Path(sys.argv[1]).resolve()
    result = execute(root, tuple(sys.argv[2:]))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if result["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
