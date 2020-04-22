#!/usr/bin/env python3

import json
import shutil
import tempfile
from pathlib import Path
import subprocess
from typing import List, Union

ROOT = Path(__file__).parent.parent


def run(command: Union[str, List[str]]) -> str:
    """Simple wrapper around subprocess.run that returns stdout and raises exceptions on errors."""
    if isinstance(command, list):
        args = command
    elif isinstance(command, str):
        args = command.split()
    else:
        raise RuntimeError(f"run command is invalid: {command}")

    # TODO: log the output
    return (
        subprocess.run(args, stdout=subprocess.PIPE, check=True).stdout.decode().strip()
    )


def transpile(schema_path: Path) -> dict:
    res = run(
        [
            "jsonschema-transpiler",
            str(schema_path),
            "--normalize-case",
            "--resolve",
            "cast",
            "--type",
            "bigquery",
        ]
    )
    schema = json.loads(res.stdout.decode())
    return schema


def transform(document: dict) -> dict:
    # TODO: normalize field names using snake casing
    # TODO: additional properties
    # TODO: pseudo maps
    # TODO: anonymous structs
    pass


# transpile all of the schemas
def transpile_schemas(output_path: Path, schema_paths: List[Path]):
    """Write schemas to directory."""
    assert output_path.is_dir()
    for path in schema_paths:
        namespace, doctype, filename = path.parts[-3:]
        version = int(filename.split(".")[-3])
        # pioneer-study schemas were done incorrectly and are ignored here
        if namespace == "schemas":
            print(f"skipping {path} due to wrong directory level")
            continue
        out = output_path / f"{namespace}.{doctype}.{version}.bq"
        with out.open("w") as fp:
            print(f"writing {out}")
            json.dump(transpile(path), fp, indent=2)
            fp.write("\n")


def load_schemas(input_path: Path):
    paths = list(input_path.glob("*.bq"))
    assert len(paths) > 0
    schemas = {}
    for path in paths:
        qualified_name = path.parts[-1][:-3]
        with path.open("r") as fp:
            schemas[qualified_name] = json.load(fp)
    print(f"loaded {len(schemas.keys())} schemas")
    return schemas


def git_stash_size():
    return len(run("git stash list").split("\n"))


def resolve_ref(ref: str) -> str:
    resolved = run(f"git rev-parse --abbrev-ref {ref}")
    if resolved != ref:
        print(f"resolved {ref} to {resolved}")
    return resolved


def _checkout_transpile_schemas(ref: str, output: Path) -> Path:
    """Checkout a revision, transpile schemas, and return to the original revision.
    
    Generates a new folder under output with the short revision of the reference.
    """
    # preconditions
    assert output.is_dir(), f"output must be a directory: {output}"
    assert (
        len(run("git diff")) == 0
    ), f"current git state must be clean, please stash changes"

    # save the current state
    original_ref = run("git rev-parse --abbrev-ref HEAD")
    rev = run(f"git rev-parse {ref}")
    print(f"transpiling schemas for ref: {ref}, rev: {rev}")

    # directory structure uses the short revision
    short_rev_len = 7
    rev_path = output / rev[:short_rev_len]
    rev_path.mkdir()

    try:
        # checkout and generate schemas
        run(f"git checkout {ref}")
        schemas = (ROOT / "schemas").glob("**/*.schema.json")
        transpile_schemas(rev_path, schemas)
    except Exception as e:
        raise e
    finally:
        return run(f"git checkout {original_ref}")

    return rev_path


def checkout_transpile_schemas(head_ref: str, base_ref: str, outdir: Path):
    """Generate schemas for the head and base revisions of the repository. This will
    generate a folder containing the generated BigQuery schemas under the
    outdir.
    """

    # resolve references (e.g. HEAD) to their branch or tag name if they exist
    resolved_head_ref = resolve_ref(head_ref)
    resolved_base_ref = resolve_ref(base_ref)

    # generate a working path that can be thrown away if errors occur
    workdir = Path(tempfile.mkdtemp())

    # Stash any changes so we can reference by real changes in the tree. If the
    # branch has in-flight changes, the changes would be ignored by the stash.
    before_stash_size = git_stash_size()
    run("git stash")
    should_apply_stash = before_stash_size != git_stash_size()
    if should_apply_stash:
        print("NOTE: uncommitted have been detected. These will be ignored.")

    try:
        head_rev_path = _checkout_transpile_schemas(resolved_head_ref, workdir)
        base_rev_path = _checkout_transpile_schemas(resolved_base_ref, workdir)
    except Exception as e:
        raise e
    finally:
        # cleanup so the environment is in the correct state
        run(f"git checkout {head_ref}")
        if should_apply_stash:
            run("git stash apply")

    # copy into the final directory in one step
    head_schemas = load_schemas(head_rev_path)
    base_schemas = load_schemas(base_rev_path)
    shutil.rmtree(outdir)
    shutil.copytree(workdir, outdir)


# TODO: options --use-document-sample, --rev-base, --rev-head, --stash
def main():
    """
    TODO:
    ```
    create a dataset with the base git revision
        f"rev_{base_revision}"
    if dataset does not exist:
        for each schema:
            create a table for each schema in base revision:
                f"{namespace}__{doctype}_v{version}"
                insert transformed documents from base revision
    get the set of modified schemas or validation documents between revisions
    for each schema in modified set:
        initialize head table with schema of the base table
            f"rev_{head_revision}__{namspace}__{doctype}_v{version}"
        insert transformed documents from head revision
        evolve schema to head revision
        insert transformed documents from head revision
        generate diff of `SELECT *` from base vs head
    generate artifacts for CI
    on user consent:
        report artifact to structured ingestion
    ```
    """
    head_ref = "HEAD"
    base_ref = "master"

    # check that the correct tools are installed
    run("jsonschema-transpiler --version")
    checkout_transpile_schemas(head_ref, base_ref, ROOT / "integration")


def test_preconditions():
    assert (ROOT / "schemas").glob(
        "**/*.schema.json"
    ), "must contain at least one schema"
    assert (ROOT / "validation").glob(
        "**/*.pass.json"
    ), "must contain at least one passing validation document"


def test_transpile():
    assert False


def test_transform():
    assert False


if __name__ == "__main__":
    main()