import io
import json
import pathlib
import re
import urllib.parse

from typing import TypedDict, Literal, Optional, List

import click
import git
import jsonschema
import rich.console
import rich.progress
import rich.traceback

rich.traceback.install(show_locals=False)

git_folder_pattern = re.compile(r"([a-zA-Z1-9_-]+)")


def git_folder_name(url: str):
    """
    Return the last part on an url without the extention
    :param url:
    :return:

    >>> git_folder_name("https://github.com/minetest-mods/i3")
    'i3'

    >>> git_folder_name("https://github.com/minetest-mods/i3.git")
    'i3'

    >>> git_folder_name("https://git.minetest.land/MineClone2/MineClone2/")
    'MineClone2'
    """
    url_parts = urllib.parse.urlparse(url)
    return url_parts.path.rstrip("/").rpartition("/")[2].rsplit('.', 1)[0]


class ConfigPackage(TypedDict):
    """
    Represent a package in the configuration file
    """
    type: Literal["git"]
    url: str
    folder_name: Optional[str]


class ConfigContent(TypedDict):
    mods: List[ConfigPackage]


class Config(TypedDict):
    content: ConfigContent


ASSUMED_REMOTE_NAME = "origin"


def update_package_git_repo(package: ConfigPackage, collection_folder: pathlib.Path, console: rich.console.Console):
    # Get the name of the folder where the package will be stored
    package_folder_name = package.get("folder_name") or git_folder_name(package["url"])

    # Get path of package folder
    package_folder = collection_folder / package_folder_name

    # Check if the
    try:
        repo = git.Repo(package_folder)
        try:
            # There are no default remote concept, so we are just assuming the remote to pull from is "origin"
            remote = repo.remote(ASSUMED_REMOTE_NAME)

            # Fetch remote changes
            remote.fetch()

            # Get remote default branch name usually "master" or "main"
            default_remote_branch = remote.refs[0].remote_head

            # Pull remote changes
            remote_pull_changes = remote.pull(default_remote_branch)
            # console.log("REMOTE PULL CHANGES:", remote_pull_changes)

            # console.log("DEFAULT REMOTE BRANCH:", default_remote_branch)

            console.log(f"[green]Updated [blue]{package['url']}")
        except ValueError:
            console.log(
                f"[red]Can't update [blue]{package['url']}[red], ",
                f"[red]remote \"origin\" do not exist")

    except git.NoSuchPathError as e:
        git.Repo.clone_from(package["url"], package_folder)
        console.log(f"[green]Cloned [blue]{package['url']}")
    except git.InvalidGitRepositoryError as e:
        console.log(
            f"[red]Can't update [blue]{package['url']}[red], folder is not a "
            f"Git repository")


@click.command()
@click.argument("config_file", type=click.File("r"))
@click.argument("collection",
                type=click.Path(file_okay=False, dir_okay=True, writable=True, readable=True, resolve_path=False,
                                allow_dash=False, path_type=pathlib.Path))
def main(config_file: io.TextIOWrapper, collection: pathlib.Path):
    # Load console and config file
    console = rich.console.Console()

    config = json.load(config_file)
    config: Config = config

    # Validate config file
    with open("config_schema.json") as config_schema_file:
        config_schema = json.load(config_schema_file)
        try:
            jsonschema.validate(config, config_schema)
        except jsonschema.ValidationError as e:
            console.log("[red] Malformed config file:", e.args[0])
            exit(1)

    mod_count = len(config["content"]["mods"])
    console.log(f"[green]Updating {mod_count} mods...")

    # Determine the collection folder
    collection_folder = collection.absolute()

    with rich.progress.Progress(rich.progress.SpinnerColumn(spinner_name="arrow3"),
                                rich.progress.TextColumn("[progress.description]{task.description}"),
                                rich.progress.BarColumn(), rich.progress.MofNCompleteColumn(),
                                rich.progress.TimeElapsedColumn(),
                                console=console) as progress:
        task_mod = progress.add_task(f"[green]Updating mods...", total=mod_count, start=False)
        task_games = progress.add_task(f"[green]Updating games...", total=3, start=False)

        progress.start_task(task_mod)
        collection_folder_mods = collection_folder / "mods"
        for mod in config["content"]["mods"]:

            if mod["type"] == "git":
                update_package_git_repo(mod, collection_folder_mods, console)
                progress.update(task_mod, advance=1)


if __name__ == '__main__':
    main()
