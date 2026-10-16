from pathlib import Path
import os
import sys
import tempfile
import subprocess

def unchecked_coyote(*args, config="", env=os.environ):
    """Run the coyote command, ignoring the return code. Use this if you are testing for an error.

    Pass config="" to use the default config. Pass config=None not to write a config file.  This
    is only useful for checking that the default config path is correct, or checking that commands
    that don't need it can run without it."""
    coyote_path = Path(__file__).resolve().parent / '..' / '..' / 'build' / 'bin' / 'coyote'

    # Fix PWD because when we call os.chdir it doesn't update the PWD environment variable
    env["PWD"] = os.getcwd()
    # Nerf the github API calls so we can't accidentally spam the real github
    if "--fake-github" not in args:
        args = ["--fake-github"] + list(args)

    def run(args):
        all_args = [str(coyote_path)] + list(args)
        print("Running " + repr(all_args))
        return subprocess.run(all_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env)
    if config is None:
        return run(args)

    if config == "":
        config = "index = \"/dev/null\"\n"

    with tempfile.NamedTemporaryFile(mode='w') as f:
        f.write(config)
        f.flush()
        args = ['--config', f.name] + list(args)

        return run(args)

def coyote(*args, config="", env=os.environ):
    """Run the coyote command, returning the result."""
    result = unchecked_coyote(*args, config=config, env=env)
    if result.returncode != 0:
        sys.stderr.write(result.stderr.decode('utf-8', 'ignore'))
        raise Exception(result.stderr.decode('utf-8', 'ignore'))
    return result


def git(*args):
    all_args = ['git'] + list(args)
    result = subprocess.run(all_args,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    if result.returncode != 0:
        sys.stderr.write(result.stderr.decode('utf-8', 'ignore'))
        raise Exception(result.stderr.decode('utf-8', 'ignore'))
    return result


def create_package(name):
    coyote('package', 'init', name)
    with open('example-file', 'w') as f: f.write('Yes, this file exists.')
    git('init')
    git('add', '.')
    git('commit', '-m', 'initial commit')


class PackageTemplate:
    def __init__(self, repo_root_name, auto_version=True):
        self.ops = []
        self.repo_root_name = repo_root_name
        self.is_version_set = False
        self.auto_version = auto_version
        self.need_commit = False


    def _append(self, command):
        self.ops.append(command)
        return self

    def version(self, v):
        self._append(('set_version', v))
        self.is_version_set = True
        return self

    def add_file(self, path, contents, executable=False):
        self._append(('add_file', path, contents, executable))
        self.need_commit = True
        return self

    def add_symlink(self, path, target):
        self._append(('add_symlink', path, target))
        self.need_commit = True
        return self

    def add_dependency(self, pkg, dep):
        self._append(('add_dependency', pkg, dep))
        self.need_commit = True
        return self

    def add_conflict(self, pkg, conflict):
        self._append(('add_conflict', pkg, conflict))
        self.need_commit = True
        return self

    def on_install(self, pkg, script):
        self._append(('on_install', pkg, script))
        self.need_commit = True
        return self

    def add_build_file(self, pkg, contents):
        self._append(('add_build_file', pkg, contents))
        self.need_commit = True
        return self

    def commit(self, msg="No message given"):
        self._append(('commit', msg))
        self.need_commit = False
        return self


    def build(self, workdir, pkg, build_version=None):
        with NewDirContext(workdir / self.repo_root_name):
            create_package(pkg)
            if self.need_commit:
                self.commit()
            if not self.is_version_set and self.auto_version:
                self.version('v1.42.0')
            for op in self.ops:
                if op[0] == 'set_version':
                    if len(op) == 1 or str(op[1]) == "":
                        raise ValueError("Version must be provided")
                    git('tag', '--annotate', '-m', "No tag message", 'coyote-' + op[1])
                elif op[0] == 'add_file':
                    target = Path(op[1])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(op[2])
                    if op[3]:
                        target.chmod(target.stat().st_mode | 0o111)
                    git('add', op[1])
                elif op[0] == 'add_symlink':
                    print("Adding symlink " + op[1])
                    target = Path(op[1])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.symlink(op[2], op[1])
                    git('add', op[1])
                elif op[0] == 'add_dependency':
                    Path(f".cypkg/{op[1]}/DEPENDS").write_text(op[2] + '\n')
                elif op[0] == 'add_conflict':
                    Path(f".cypkg/{op[1]}/CONFLICTS").write_text(op[2] + '\n')
                elif op[0] == 'on_install':
                    Path(f".cypkg/{op[1]}/on-install").write_text(op[2] + '\n')
                    Path(f".cypkg/{op[1]}/on-install").chmod(0o755)
                elif op[0] == 'add_build_file':
                    Path(f".cypkg/{op[1]}/build").write_text(op[2] + '\n')
                    Path(f".cypkg/{op[1]}/build").chmod(0o755)
                elif op[0] == 'commit':
                    git('add', '.')
                    git('commit', '-m', op[1])
            args = ['package', 'build', pkg]
            if build_version is not None: args.append(build_version)
            package_name = coyote(*args).stdout.decode('utf-8').strip()
            os.rename(package_name, workdir / package_name)
            return workdir / package_name


def build_legacy_build_script_package(workdir, name, version, files, depends=''):
    """Build a .cypkg in the layout that older versions of coyote made with a build script.

    Those versions stored the metadata entries as ".CYMETA/<field>", without the "./" prefix
    that default packages have. We build the archive by hand so that the test does not depend
    on the current `package build` behaviour."""
    import io
    import tarfile

    def add(tar, arcname, contents):
        data = contents.encode('utf-8')
        info = tarfile.TarInfo(arcname)
        info.size = len(data)
        info.mode = 0o644
        tar.addfile(info, io.BytesIO(data))

    package_path = Path(workdir) / f"{name}-{version}.cypkg"
    with tarfile.open(package_path, 'w:gz', format=tarfile.GNU_FORMAT) as tar:
        for path, contents in files.items():
            add(tar, path, contents)
        cymeta_dir = tarfile.TarInfo('.CYMETA')
        cymeta_dir.type = tarfile.DIRTYPE
        cymeta_dir.mode = 0o755
        tar.addfile(cymeta_dir)
        add(tar, '.CYMETA/NAME', name)
        add(tar, '.CYMETA/VERSION', version)
        add(tar, '.CYMETA/DEPENDS', depends)
        add(tar, '.CYMETA/CONFLICTS', '')
    return package_path


def build_package(workdir, repo_root, name):
    return PackageTemplate(repo_root) \
        .build(workdir, name)


class DirContext:
    def __init__(self, path):
        self.path = Path(path)

    def __enter__(self):
        self.currentdir = Path.cwd()
        os.chdir(self.path)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        os.chdir(self.currentdir)


def unpack(package):
    return subprocess.run(['tar', 'xzf', str(package)],
                          stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE)


class NewDirContext(DirContext):
    def __init__(self, path):
        super().__init__(path)
        self.path.mkdir()
class CoyoteTestContext:
    def __enter__(self):
        self.currentdir = Path.cwd()
        self.tmpdir = tempfile.TemporaryDirectory()
        os.chdir(self.tmpdir.name)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.tmpdir.cleanup()
        os.chdir(self.currentdir)

    def path(self, *args):
        return Path(self.tmpdir.name, *args)

class NewProjectContext(CoyoteTestContext):
    def __init__(self, name, tech_stack='empty'):
        super().__init__()
        self.name = name
        self.tech_stack = tech_stack

    def __enter__(self):
        self.parent_path = Path.cwd()
        coyote('init', self.tech_stack, self.name)
        os.chdir(self.name)
        self.project_path = Path.cwd()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        os.chdir(self.parent_path)

    def path(self, *args):
        return Path(self.project_path, *args)

class Index:
    def __init__(self, source_path, target_path):
        self.source_path = source_path
        self.target_path = target_path

class Indexer:
    def __init__(self, *packages):
        self.packages = packages

    def add_package(self, package):
        self.packages.append(package)
        return self

    def build(self, ctx):
        index = Index(ctx.path()/"index-source", ctx.path()/"index.cyi")
        index.source_path.write_text('\n'.join(str(package) for package in self.packages))
        coyote('index', 'build', index.source_path, index.target_path)
        return index
