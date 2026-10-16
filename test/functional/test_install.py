from utils import *
from http_server import PackageServer

def test_install_into_empty_project():
    with CoyoteTestContext() as ctx:
        package_path = PackageTemplate('test-package-root') \
            .add_file('canary', 'This is a test package') \
            .build(ctx.path(), 'my-dependency')
        index = Indexer(package_path).build(ctx)
        with NewProjectContext('my-new-project'):
            coyote('install', 'my-dependency', '--index', index.target_path)
            assert(Path('canary').is_file())

def test_install_from_remote_index():
    with CoyoteTestContext() as ctx:
        package_path = PackageTemplate('test-package-root') \
            .add_file('canary', 'This is a test package') \
            .build(ctx.path(), 'my-dependency')
        with PackageServer(ctx.path()) as server:
            location = server.url(package_path.name)
            index = Indexer(location).build(ctx)
            with NewProjectContext('my-new-project'):
                coyote('install', 'my-dependency', '--index', server.url(index.target_path.name))
                assert(Path('canary').is_file())


def test_install_into_project_with_package_already_installed_passes():
    with CoyoteTestContext() as ctx:
        package_path = PackageTemplate('test-package-root') \
            .add_file('canary', 'This is a test package') \
            .build(ctx.path(), 'my-dependency')
        index = Indexer(package_path).build(ctx)
        with NewProjectContext('my-new-project'):
            coyote('install', 'my-dependency', '--index', index.target_path)
            coyote('install', 'my-dependency', '--index', index.target_path)

def test_install_into_project_installs_dependencies():
    with CoyoteTestContext() as ctx:
        package_a_path = PackageTemplate('package-a-root') \
            .add_dependency('dependency', 'upstream-dependency') \
            .build(ctx.path(), 'dependency')
        package_b_path = PackageTemplate('package-b-root') \
            .add_file('upstream-file', 'This is a test package') \
            .build(ctx.path(), 'upstream-dependency')
        index = Indexer(package_a_path, package_b_path).build(ctx)
        with NewProjectContext('my-new-project'):
            coyote('install', 'dependency', '--index', index.target_path)
            assert(Path('upstream-file').is_file())

def test_install_into_project_installs_dependencies_recursively():
    with CoyoteTestContext() as ctx:
        package_a_path = PackageTemplate('package-a-root') \
            .add_dependency('dependency', 'upstream-dependency') \
            .build(ctx.path(), 'dependency')
        package_b_path = PackageTemplate('package-b-root') \
            .add_dependency('upstream-dependency', 'grand-dependency') \
            .build(ctx.path(), 'upstream-dependency')
        package_c_path = PackageTemplate('package-c-root') \
            .add_file('canary', 'This is a test package') \
            .build(ctx.path(), 'grand-dependency')
        index = Indexer(package_a_path, package_b_path, package_c_path).build(ctx)
        with NewProjectContext('my-new-project'):
            coyote('install', 'dependency', '--index', index.target_path)
            assert(Path('canary').is_file())


def test_install_records_the_installation():
    with CoyoteTestContext() as ctx:
        package_path = PackageTemplate('test-package-root') \
            .build(ctx.path(), 'my-dependency')
        index = Indexer(package_path).build(ctx)
        with NewProjectContext('my-new-project'):
            coyote('install', 'my-dependency', '--index', index.target_path)
            assert(Path('.coyote/installed').read_text().strip() == 'my-dependency=v1.42.0')


def test_install_records_the_installation_of_multiple_packages():
    with CoyoteTestContext() as ctx:
        package_a_path = PackageTemplate('package-a-root') \
            .build(ctx.path(), 'my-dependency')
        package_b_path = PackageTemplate('package-b-root') \
            .build(ctx.path(), 'my-other-dependency')
        index = Indexer(package_a_path, package_b_path).build(ctx)
        with NewProjectContext('my-new-project'):
            coyote('install', 'my-dependency', '--index', index.target_path)
            coyote('install', 'my-other-dependency', '--index', index.target_path)
            assert(Path('.coyote/installed').read_text().strip() == 'my-dependency=v1.42.0\nmy-other-dependency=v1.42.0')

def test_install_dependencies_recursively_with_conflicts_fails():
    with CoyoteTestContext() as ctx:
        package_a_path = PackageTemplate('package-a-root') \
            .add_file('canary', 'Any contents') \
            .build(ctx.path(), 'dependency')

        package_b_path = PackageTemplate('package-b-root') \
            .add_dependency('another-dependency', 'conflicting-package') \
            .build(ctx.path(), 'another-dependency')
        package_c_path = PackageTemplate('package-c-root') \
            .add_conflict('conflicting-package', 'dependency') \
            .build(ctx.path(), 'conflicting-package')

        index = Indexer(package_a_path, package_b_path, package_c_path).build(ctx)
        with NewProjectContext('my-new-project'):
            coyote('install', 'dependency', '--index', index.target_path)
            cmd = unchecked_coyote('install', 'another-dependency', '--index', index.target_path)
            assert(cmd.returncode == 1)

def test_install_dependencies_recursively_with_conflicts_fails_without_installing_anything():
    with CoyoteTestContext() as ctx:
        package_a_path = PackageTemplate('package-a-root') \
            .add_file('just-a-file', 'Any contents') \
            .build(ctx.path(), 'dependency')

        package_b_path = PackageTemplate('package-b-root') \
            .add_dependency('another-dependency', 'conflicting-package') \
            .add_file('canary', 'This file should not be installed') \
            .build(ctx.path(), 'another-dependency')
        package_c_path = PackageTemplate('package-c-root') \
            .add_conflict('grand-dependency', 'dependency') \
            .build(ctx.path(), 'grand-dependency')

        index = Indexer(package_a_path, package_b_path, package_c_path).build(ctx)
        with NewProjectContext('my-new-project'):
            cmd = unchecked_coyote('install', 'another-dependency', '--index', index.target_path)
            assert(cmd.returncode == 1)
            assert(not Path('canary').is_file())

def test_install_runs_on_install():
    with CoyoteTestContext() as ctx:
        package_path = PackageTemplate('test-package-root') \
            .on_install('my-dependency', '#!/bin/sh\ntouch canary\n') \
            .build(ctx.path(), 'my-dependency')
        index = Indexer(package_path).build(ctx)
        with NewProjectContext('my-new-project'):
            coyote('install', 'my-dependency', '--index', index.target_path)
            assert(Path('canary').is_file())

def test_install_runs_on_install_is_skipped_if_already_installed():
    with CoyoteTestContext() as ctx:
        package_path = PackageTemplate('test-package-root') \
            .on_install('my-dependency', '#!/bin/sh\nif [ -f canary ]; then exit 1; else touch canary; fi\n') \
            .build(ctx.path(), 'my-dependency')
        index = Indexer(package_path).build(ctx)
        with NewProjectContext('my-new-project'):
            coyote('install', 'my-dependency', '--index', index.target_path)
            coyote('install', 'my-dependency', '--index', index.target_path)
            assert(Path('canary').is_file())

def test_install_runs_on_install_is_rerun_if_reinstall():
    with CoyoteTestContext() as ctx:
        package_path = PackageTemplate('test-package-root') \
            .on_install('my-dependency', '#!/bin/sh\necho -n "bun" >> canary\n') \
            .build(ctx.path(), 'my-dependency')
        index = Indexer(package_path).build(ctx)
        with NewProjectContext('my-new-project'):
            coyote('install', 'my-dependency', '--index', index.target_path)
            coyote('install', 'my-dependency', '--index', index.target_path, '--reinstall')
            assert(Path('canary').read_text().strip() == 'bunbun')


def notest_install_a_remote_package():
    with CoyoteTestContext() as ctx:
        package_path = PackageTemplate('test-package-root') \
            .add_file('canary', 'This is a test package') \
            .build(ctx.path(), 'my-dependency')
        with PackageServer(ctx.path()) as server:
            location = server.url(package_path.name)
            index = Indexer(location).build(ctx)
            with NewProjectContext('my-new-project'):
                coyote('install', 'my-dependency', '--index', index.target_path)
                assert(Path('canary').is_file())


def test_install_picks_latest_version_when_multiple_versions_in_index():
    with CoyoteTestContext() as ctx:
        # Build two versions of the same package with different canary contents
        # Note: add_file + commit must come before version so the file is committed before tagging
        package_v1 = PackageTemplate('test-package-root') \
            .add_file('canary', 'version 1') \
            .commit('add canary v1') \
            .version('v1.0.0') \
            .build(ctx.path(), 'my-dependency')
        package_v2 = PackageTemplate('test-package-root-v2') \
            .add_file('canary', 'version 2') \
            .commit('add canary v2') \
            .version('v2.0.0') \
            .build(ctx.path(), 'my-dependency')
        # Include both versions in the index
        index = Indexer(package_v1, package_v2).build(ctx)
        with NewProjectContext('my-new-project'):
            coyote('install', 'my-dependency', '--index', index.target_path)
            # Should install the latest version (v2.0.0)
            assert(Path('canary').read_text() == 'version 2')


def test_install_explicit_version():
    with CoyoteTestContext() as ctx:
        # Build two versions of the same package with different canary contents
        # Note: add_file + commit must come before version so the file is committed before tagging
        package_v1 = PackageTemplate('test-package-root') \
            .add_file('canary', 'version 1') \
            .commit('add canary v1') \
            .version('v1.0.0') \
            .build(ctx.path(), 'my-dependency')
        package_v2 = PackageTemplate('test-package-root-v2') \
            .add_file('canary', 'version 2') \
            .commit('add canary v2') \
            .version('v2.0.0') \
            .build(ctx.path(), 'my-dependency')
        # Include both versions in the index
        index = Indexer(package_v1, package_v2).build(ctx)
        with NewProjectContext('my-new-project'):
            # Explicitly install v1.0.0
            coyote('install', 'my-dependency@v1.0.0', '--index', index.target_path)
            assert(Path('canary').read_text() == 'version 1')


def test_install_explicit_version_not_found():
    with CoyoteTestContext() as ctx:
        package_v1 = PackageTemplate('test-package-root') \
            .add_file('canary', 'version 1') \
            .commit('add canary') \
            .version('v1.0.0') \
            .build(ctx.path(), 'my-dependency')
        index = Indexer(package_v1).build(ctx)
        with NewProjectContext('my-new-project'):
            cmd = unchecked_coyote('install', 'my-dependency@v9.9.9', '--index', index.target_path)
            assert(cmd.returncode != 0)
            assert('version v9.9.9 not found' in cmd.stderr.decode('utf-8') or
                   'not found' in cmd.stderr.decode('utf-8'))

def test_install_legacy_build_script_package():
    # Older versions of coyote stored build-script package metadata as ".CYMETA/<field>"
    # instead of "./.CYMETA/<field>". Those packages must still install, and the metadata
    # must not appear in the project.
    with CoyoteTestContext() as ctx:
        package_path = build_legacy_build_script_package(
            ctx.path(), 'legacy-package', 'v1.2.3',
            {'canary': 'This is a legacy package'})
        index = Indexer(package_path).build(ctx)
        with NewProjectContext('my-new-project'):
            coyote('install', 'legacy-package', '--index', index.target_path)
            assert(Path('canary').read_text() == 'This is a legacy package')
            assert(not Path('.CYMETA').exists())
