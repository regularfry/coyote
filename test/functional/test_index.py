from utils import *
import json

from http_server import PackageServer

def test_index_creates_file():
    with CoyoteTestContext() as ctx:
        package_path = PackageTemplate('test-package-root') \
            .add_file('canary', 'This is a test package') \
            .build(ctx.path(), 'my-chosen-tech-stack')
        index_source_path = ctx.path()/"index-source"
        index_source_path.write_text(str(package_path))
        target_path = ctx.path()/"index.cyi"

        coyote('index', 'build', index_source_path, target_path)

        assert(target_path.is_file())

def test_index_lists_conflicts():
    with CoyoteTestContext() as ctx:
        package_path1 = PackageTemplate('test-package-root') \
            .add_conflict('conflicted-package', 'other-package') \
            .build(ctx.path(), 'conflicted-package')
        package_path2 = PackageTemplate('test-other-package') \
            .build(ctx.path(), 'other-package')

        index_source_path = ctx.path()/"index-source"
        index_source_path.write_text('\n'.join(str(package_path) for package_path in [package_path1, package_path2]))
        target_path = ctx.path()/"index.cyi"

        coyote('index', 'build', index_source_path, target_path)

        index = json.loads(target_path.read_text())
        assert(index['packages']['conflicted-package']['conflicts'] == ['other-package'])


def test_conflicts_are_reflected():
    with CoyoteTestContext() as ctx:
        package_path1 = PackageTemplate('test-package-root') \
            .add_conflict('conflicted-package', 'other-package') \
            .build(ctx.path(), 'conflicted-package')
        package_path2 = PackageTemplate('test-other-package') \
            .build(ctx.path(), 'other-package')

        index_source_path = ctx.path()/"index-source"
        index_source_path.write_text('\n'.join(str(package_path) for package_path in [package_path1, package_path2]))
        target_path = ctx.path()/"index.cyi"

        coyote('index', 'build', index_source_path, target_path)

        index = json.loads(target_path.read_text())
        assert(index['packages']['other-package']['conflicts'] == ['conflicted-package'])

# Temporarily disabled while I figure out how to test this properly, given that github downloads are involved
def notest_index_lists_remote_package():
    with CoyoteTestContext() as ctx:
        package_path = PackageTemplate('test-package-root') \
            .build(ctx.path(), 'my-chosen-tech-stack')

        with PackageServer(ctx.path()) as server:
            location = server.url(package_path.name)
            index_source_path = ctx.path()/"index-source"
            index_source_path.write_text(location)
            target_path = ctx.path()/"index.cyi"

            coyote('index', 'build', index_source_path, target_path)

            index = json.loads(target_path.read_text())
            assert(index['packages']['my-chosen-tech-stack']['location'] == location)

def test_index_location_relative_to_index_file():
    with CoyoteTestContext() as ctx:
        package_path = PackageTemplate('test-package-root') \
            .build(ctx.path(), 'my-chosen-tech-stack')
        index_source_path = ctx.path()/"subdir"/"index-source"
        index_source_path.parent.mkdir(parents=True, exist_ok=True)
        index_source_path.write_text(f"../{str(package_path.name)}")
        target_path = ctx.path()/"index.cyi"
        # now what should end up in the index for the location of the package is
        # the resolved absolute path to the package, not the relative path

        coyote('index', 'build', index_source_path, target_path)
        index = json.loads(target_path.read_text())
        assert(index['packages']['my-chosen-tech-stack']['location'] == str(package_path.absolute()))

def test_error_if_file_doesnt_exist():
    with CoyoteTestContext() as ctx:
        index_source_path = ctx.path()/"index-source"
        index_source_path.write_text("doesnt-exist")
        target_path = ctx.path()/"index.cyi"

        cmd = unchecked_coyote('index', 'build', index_source_path, target_path)
        assert("package file missing: " in cmd.stderr.decode('utf-8'))

def test_index_release_fails_with_no_source_file():
    with CoyoteTestContext() as ctx:
        cmd = unchecked_coyote('index', 'release', 'no-such-file', "doesntmatter")
        assert("index source file not found: no-such-file" in cmd.stderr.decode('utf-8'))

# coyote index release needs to be run in a checkout of the index repo so that it can make a release commit
# and upload the built index as a release
def test_index_release_fails_if_not_in_git_repo():
    with CoyoteTestContext() as ctx:
        src_path = ctx.path()/'index-src'
        src_path.write_text("anything")
        cmd = unchecked_coyote('index', 'release', 'index-src', "doesntmatter")
        assert("not in a git repository" in cmd.stderr.decode('utf-8'))


def test_index_stores_multiple_versions_of_same_package():
    with CoyoteTestContext() as ctx:
        # Build two versions of the same package
        package_v1 = PackageTemplate('test-package-v1') \
            .version('v1.0.0') \
            .add_file('canary', 'version 1') \
            .build(ctx.path(), 'my-package')
        package_v2 = PackageTemplate('test-package-v2') \
            .version('v2.0.0') \
            .add_file('canary', 'version 2') \
            .build(ctx.path(), 'my-package')

        index_source_path = ctx.path()/"index-source"
        index_source_path.write_text('\n'.join([str(package_v1), str(package_v2)]))
        target_path = ctx.path()/"index.cyi"

        coyote('index', 'build', index_source_path, target_path)

        index = json.loads(target_path.read_text())
        # The index should have both versions
        assert('my-package' in index['packages'])
        pkg_entry = index['packages']['my-package']
        assert('versions' in pkg_entry)
        assert(len(pkg_entry['versions']) == 2)
        versions = {v['version']: v for v in pkg_entry['versions']}
        assert('v1.0.0' in versions)
        assert('v2.0.0' in versions)


def test_index_latest_version_is_determined_correctly():
    with CoyoteTestContext() as ctx:
        # Build versions where semantic versioning matters (1.0.11 > 1.0.2)
        package_v1 = PackageTemplate('test-package-v1') \
            .version('v1.0.2') \
            .build(ctx.path(), 'my-package')
        package_v2 = PackageTemplate('test-package-v2') \
            .version('v1.0.11') \
            .build(ctx.path(), 'my-package')
        package_v15 = PackageTemplate('test-package-v15') \
            .version('v1.0.5') \
            .build(ctx.path(), 'my-package')

        index_source_path = ctx.path()/"index-source"
        # Add in non-sorted order
        index_source_path.write_text('\n'.join([str(package_v2), str(package_v1), str(package_v15)]))
        target_path = ctx.path()/"index.cyi"

        coyote('index', 'build', index_source_path, target_path)

        index = json.loads(target_path.read_text())
        pkg_entry = index['packages']['my-package']
        # The latest should be v1.0.11 (highest by semantic versioning, not asciibetic)
        assert(pkg_entry['version'] == 'v1.0.11')



def test_index_reads_metadata_from_legacy_build_script_package():
    # Older versions of coyote stored build-script package metadata as ".CYMETA/<field>"
    # instead of "./.CYMETA/<field>". The index must still read those packages.
    with CoyoteTestContext() as ctx:
        package_path = build_legacy_build_script_package(
            ctx.path(), 'legacy-package', 'v1.2.3',
            {'canary': 'This is a legacy package'},
            depends='upstream-dependency\n')
        upstream_path = PackageTemplate('upstream-root') \
            .build(ctx.path(), 'upstream-dependency')

        index = Indexer(package_path, upstream_path).build(ctx)

        index_data = json.loads(index.target_path.read_text())
        pkg_entry = index_data['packages']['legacy-package']
        assert(pkg_entry['name'] == 'legacy-package')
        assert(pkg_entry['version'] == 'v1.2.3')
        assert(pkg_entry['dependencies'] == ['upstream-dependency'])
