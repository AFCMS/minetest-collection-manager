import io
import json
import pathlib
import re
import urllib.parse
import urllib.request
from typing import TypedDict, Literal, Optional, List, Union, NoReturn, TextIO, Tuple

import click
import git
import jsonschema
import rich.console
import rich.progress
import rich.traceback

rich.traceback.install(show_locals=False)

git_folder_pattern = re.compile(r"([a-zA-Z1-9_-]+)")


# TODO: better schema validation
# https://stackoverflow.com/questions/38717933/jsonschema-attribute-conditionally-required


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


def cdb_package_infos(url: str) -> Optional[Tuple[str, str]]:
    """
    Return the author and the package name from a CDB URL

    >>> cdb_package_infos("https://content.minetest.net/packages/AFCM/subway_miner")
    ('AFCM', 'subway_miner')

    >>> cdb_package_infos("https://content.minetest.net/packages/davidthecreator/rangedweapons/")
    ('davidthecreator', 'rangedweapons')
    """
    url_parts = urllib.parse.urlparse(url)
    url_path = url_parts.path.strip("/")
    url_path_parts = url_path.split("/")
    if len(url_path_parts) != 3 or url_path_parts[0] != "packages":
        return None
    return url_path_parts[1], url_path_parts[2]


PackageCategory = Literal["mods", "client_mods", "games", "texture_packs"]
PackageType = Literal["git", "cdb"]


class ConfigPackage(TypedDict):
    """
    Represent a package in the configuration file
    """
    type: PackageType
    url: str
    folder_name: Optional[str]
    git_remote_branch: Optional[str]


class ConfigContent(TypedDict):
    mods: List[ConfigPackage]
    games: List[ConfigPackage]


class Config(TypedDict):
    content: ConfigContent
    auto_sort: Optional[bool]


class CDBPackage(TypedDict):
    author: str
    name: str
    release: int
    short_description: str
    thumbnail: str
    title: str
    type: Literal["mod", "game", "txp"]


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

            # Get remote default branch name usually "master" or "main" or use configured branch name
            default_remote_branch = package.get("git_remote_branch") or remote.refs[0].remote_head

            # Pull remote changes
            remote.pull(default_remote_branch)

            # remote_pull_changes = remote.pull(default_remote_branch)
            # console.log("REMOTE PULL CHANGES:", remote_pull_changes)
            # console.log("DEFAULT REMOTE BRANCH:", default_remote_branch)

            # Update submodules
            repo.submodule_update()

            console.log(f"[green]Updated [blue]{package['url']}")
        except ValueError:
            console.log(
                f"[red]Can't update [blue]{package['url']}[red], ",
                f"[red]remote \"origin\" do not exist")

    except git.NoSuchPathError:
        git.Repo.clone_from(package["url"], package_folder)
        console.log(f"[green]Cloned [blue]{package['url']}")
    except git.InvalidGitRepositoryError:
        console.log(
            f"[red]Can't update [blue]{package['url']}[red], folder is not a "
            f"Git repository")
    except git.GitCommandError as e:
        console.log(
            f"[red]Can't update [blue]{package['url']}[red], "
            f"[red]Git command failed: {e.stderr}")


def get_cdb_package_list(url: str) -> List[CDBPackage]:
    result = urllib.request.urlopen(url + "/api/packages/?type=mod&type=game&type=txp")
    return result


def update_package_cdb(package: ConfigPackage, collection_folder: pathlib.Path, console: rich.console.Console):
    pass


def get_validated_config(config_file: TextIO, console: rich.console.Console) -> Union[Config, NoReturn]:
    """
    Get validated config from file or crash with output to console
    """

    config: Config
    try:
        config = json.load(config_file)
    except json.JSONDecodeError as e:
        console.log("[red] Malformed config file:", e.args[0])
        exit(1)

    # Validate config file
    with open("config_schema.json") as config_schema_file:
        config_schema = json.load(config_schema_file)
        try:
            jsonschema.validate(config, config_schema)
        except jsonschema.ValidationError as e:
            console.log("[red] Malformed config file:", e.args[0])
            exit(1)

    return config


# TODO: use dedicated rich-click when availlable

@click.group()
def cli():
    """
    Minetest Collection Manager
    """
    pass


@cli.command()
@click.argument("config_file",
                type=click.Path(file_okay=True, dir_okay=False, writable=True, readable=True, resolve_path=True,
                                allow_dash=False, path_type=pathlib.Path))
@click.argument("category", type=click.Choice(["mods", "client_mods", "games", "texture_packs"], case_sensitive=False))
@click.argument("package_type", type=click.Choice(["git", "cdb"], case_sensitive=False))
@click.argument("url", type=str)
@click.option("--folder-name", type=str)
@click.option("--git-remote-branch", type=str, default=None)
@click.option("--sort", is_flag=True, show_default=True, default=False)
def add_package(config_file: pathlib.Path, category: PackageCategory, package_type: PackageType, url: str,
                folder_name: Optional[str], git_remote_branch: Optional[str], sort: bool):
    """
    Add package to given config file
    """
    # Load console and config file
    console = rich.console.Console()

    with config_file.open("r") as f:
        config = get_validated_config(f, console)

    # Check if a package with the same url is already present for the category
    is_url_present = any(p["url"] == url for p in config["content"][category])
    if is_url_present:
        console.log("[red] Package with same URL already exist for the category")
        exit(1)

    # Check if a package with the same folder name is already present for the category
    final_folder_name = folder_name or git_folder_name(url)
    is_folder_name_present = any(
        (p.get("folder_name") or git_folder_name(p["url"])) == final_folder_name for p in config["content"][category])
    if is_folder_name_present:
        console.log("[red] Package with same folder name already exist")
        exit(1)

    config["content"][category].append({
        "type": package_type,
        "url": url
    })

    if git_remote_branch:
        config["content"][category][-1]["git_remote_branch"] = git_remote_branch

    if sort or config.get("auto_sort"):
        config["content"][category].sort(key=lambda e: e["url"])

    with config_file.open("w") as f:
        json.dump(config, f, indent="\t")


@cli.command()
@click.argument("config_file",
                type=click.Path(file_okay=True, dir_okay=False, writable=True, readable=True, resolve_path=True,
                                allow_dash=False, path_type=pathlib.Path))
@click.argument("category", type=click.Choice(["mods", "client_mods", "games", "texture_packs"], case_sensitive=False))
@click.argument("package_type", type=click.Choice(["git", "cdb"], case_sensitive=False))
@click.argument("url", type=str)
def remove_package(config_file: pathlib.Path, category: PackageCategory, package_type: PackageType, url: str):
    """
    Remove package from given config file
    """
    # Load console and config file
    console = rich.console.Console()

    with config_file.open("r") as f:
        config = get_validated_config(f, console)

    config["content"][category] = [d for d in config["content"][category] if
                                   d.get("url") != url or d.get("type") != package_type]

    with config_file.open("w") as f:
        json.dump(config, f, indent="\t")


@cli.command()
@click.argument("config_file", type=click.File("r"))
@click.argument("collection",
                type=click.Path(file_okay=False, dir_okay=True, writable=True, readable=True, resolve_path=True,
                                allow_dash=False, path_type=pathlib.Path))
def update(config_file: io.TextIOWrapper, collection: pathlib.Path):
    """
    Update packages in given collection folder using given config file
    """
    # Load console and config file
    console = rich.console.Console()

    config = get_validated_config(config_file, console)

    mod_count = len(config["content"]["mods"])
    csm_count = len(config["content"]["client_mods"])
    game_count = len(config["content"]["games"])
    txp_count = len(config["content"]["texture_packs"])
    console.log(f"[green]Updating {mod_count} mods...")

    # Determine the collection folder
    collection_folder = collection.absolute()

    with rich.progress.Progress(rich.progress.SpinnerColumn(spinner_name="arrow3"),
                                rich.progress.TextColumn("[progress.description]{task.description}"),
                                rich.progress.BarColumn(), rich.progress.MofNCompleteColumn(),
                                rich.progress.TimeElapsedColumn(),
                                console=console) as progress:
        task_mods = progress.add_task(f"[green]Updating mods...", total=mod_count, start=(mod_count == 0))
        task_client_mods = progress.add_task(f"[green]Updating client mods...", total=csm_count, start=(csm_count == 0))
        task_games = progress.add_task(f"[green]Updating games...", total=game_count, start=(game_count == 0))
        task_texturepacks = progress.add_task(f"[green]Updating texture packs...", total=txp_count,
                                              start=(txp_count == 0))

        if mod_count == 0:
            progress.stop_task(task_mods)
        if game_count == 0:
            progress.stop_task(task_games)
        if csm_count == 0:
            progress.stop_task(task_client_mods)
        if txp_count == 0:
            progress.stop_task(task_texturepacks)

        def update_packages(task: rich.progress.TaskID, package_category: PackageCategory):
            progress.start_task(task)
            for package in config["content"][package_category]:

                if package["type"] == "git":
                    update_package_git_repo(package, collection_folder / package_category, console)
                    # time.sleep(1)
                    progress.update(task, advance=1)

        update_packages(task_mods, "mods")
        update_packages(task_client_mods, "client_mods")
        update_packages(task_games, "games")
        update_packages(task_texturepacks, "texture_packs")


def sync_folders(input_path: pathlib.Path, output_path: pathlib.Path, name: str, console: rich.console.Console):
    """
    Symlink all folders from input path to output path if possible, log results
    """
    if input_path.exists() and input_path.is_dir():
        for p in input_path.iterdir():
            if p.is_dir():
                if not output_path.exists():
                    output_path.mkdir()
                if (output_path / p.name).exists():
                    if (output_path / p.name).is_symlink() and (output_path / p.name).readlink() == p:
                        console.log(f"[green] ({name}) [blue]{p.name}[green] is already linked in collection")
                    else:
                        console.log(f"[red] ({name}) Cant link [blue]{p.name}[red], folder already exist in collection")
                else:
                    (output_path / p.name).symlink_to(p)
                    console.log(f"[green] ({name}) Linked [blue]{p.name}[green] in collection")


@cli.command()
@click.argument("collection",
                type=click.Path(file_okay=False, dir_okay=True, writable=True, readable=True, resolve_path=True,
                                allow_dash=False, path_type=pathlib.Path))
@click.argument("dev_directory",
                type=click.Path(file_okay=False, dir_okay=True, writable=True, readable=True, resolve_path=True,
                                allow_dash=False, path_type=pathlib.Path))
def sync_dev(collection: pathlib.Path, dev_directory: pathlib.Path):
    """
    Sync a development folder with a collection folder by symlinking all folders if possible
    """
    # Load console
    console = rich.console.Console()

    for cat in zip(["mods", "client_mods", "games", "texture_packs"], ["mods", "clientmods", "games", "textures"]):
        sync_folders(dev_directory / cat[0], collection / cat[0], cat[0], console)


@cli.command()
@click.argument("collection",
                type=click.Path(file_okay=False, dir_okay=True, writable=True, readable=True, resolve_path=True,
                                allow_dash=False, path_type=pathlib.Path))
@click.argument("user_directory",
                type=click.Path(file_okay=False, dir_okay=True, writable=True, readable=True, resolve_path=True,
                                allow_dash=False, path_type=pathlib.Path))
def sync(collection: pathlib.Path, user_directory: pathlib.Path):
    """
    Sync a collection folder with a Minetest user directory
    """
    # Load console
    console = rich.console.Console()
    for cat in zip(["mods", "client_mods", "games", "texture_packs"], ["mods", "clientmods", "games", "textures"]):
        sync_folders(collection / cat[0], user_directory / cat[1], cat[0], console)


@cli.command()
@click.argument("config_file", type=click.File("w+"))
@click.option("--schema", is_flag=True, default=False)
@click.option("--auto-sort", is_flag=True, default=False)
def create_config(config_file: io.TextIOWrapper, schema: bool, auto_sort: bool):
    # Load console
    console = rich.console.Console()

    json.dump({
        "$schema": schema and str(pathlib.Path(__file__).parent / "config_schema.json") or None,
        "content": {
            "mods": [],
            "client_mods": [],
            "games": [],
            "texture_packs": []
        },
        "auto_sort": auto_sort
    }, config_file, indent="\t")

    console.log(f"[green] Config file created (schema={schema}, auto_sort={auto_sort})")


if __name__ == "__main__":
    cli()
