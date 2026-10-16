package adapters

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"fmt"
	"io"
	"os"
	"os/exec"
	"sort"
	"strings"
	"text/template"

	core "github.com/nhsdigital/coyote/internal/core"
)

// metadataDirName is the directory in a package that holds its metadata
// (NAME, VERSION, DEPENDS, CONFLICTS, on-install).
const metadataDirName = ".CYMETA"

// metadataArchivePrefix is the member-name prefix for metadata inside a .cypkg archive.
//
// Do not remove the "./". GNU tar matches member names exactly, so "./.CYMETA/NAME" and
// ".CYMETA/NAME" are different paths to it. bsdtar (the default on macOS) ignores the
// prefix, so tests on macOS do not show the problem. Only a run with GNU tar (Linux) fails.
// See commit 351d156.
//
// Every package that coyote builds must store its metadata under this prefix:
//   - buildDefaultPackage gets the prefix because it archives ".".
//   - buildWithBuildScript adds the metadata with this prefix explicitly.
const metadataArchivePrefix = "./" + metadataDirName + "/"

// legacyMetadataArchivePrefix is the prefix that older versions of coyote used for
// packages built with a build script. ReadMetadata and Apply accept it so that those
// packages still work. Do not use it for new packages.
const legacyMetadataArchivePrefix = metadataDirName + "/"

func CopyFile(src, dst string) {
	srcFile, err := os.Open(src)
	if err != nil {
		panic(err)
	}
	defer srcFile.Close()
	dstFile, err := os.Create(dst)
	if err != nil {
		panic(err)
	}
	defer dstFile.Close()
	_, err = io.Copy(dstFile, srcFile)
	if err != nil {
		panic(err)
	}
	// Set the permission bits
	srcInfo, err := os.Stat(src)
	if err != nil {
		panic(err)
	}
	err = os.Chmod(dst, srcInfo.Mode())
	if err != nil {
		panic(err)
	}
}

func fileExists(filename string) bool {
	_, err := os.Stat(filename)
	return !os.IsNotExist(err)
}

func CopyFileIfExist(src, dst string) {
	if fileExists(src) {
		CopyFile(src, dst)
	}
}

type PackageTarFile struct {
	Filename string
}

type PackageTarFileProvider struct{}

func NewPackageTarFileProvider() PackageTarFileProvider {
	return PackageTarFileProvider{}
}

func NewPackageFile(filename string) PackageTarFile {
	return PackageTarFile{Filename: filename}
}

func (p PackageTarFileProvider) Open(location string) core.PackageFile {
	return NewPackageFile(location)
}

/*
Read a metadata field from the file.

	Missing fields return an empty string, which is valid for (for instance) the on-install field

	Both metadataArchivePrefix and legacyMetadataArchivePrefix are checked, so packages
	built by older versions of coyote still work. See metadataArchivePrefix for why the
	prefix matters.
*/
func (p PackageTarFile) ReadMetadata(field string) string {
	for _, prefix := range []string{metadataArchivePrefix, legacyMetadataArchivePrefix} {
		entry := prefix + field
		fileCheck := exec.Command("tar", "-tf", p.Filename, entry)
		if err := fileCheck.Run(); err != nil {
			continue
		}
		cmd := exec.Command("tar", "-xOf", p.Filename, entry)
		output, err := cmd.Output()
		if err != nil {
			panic(err)
		}
		return strings.TrimSpace(string(output))
	}
	return ""
}

func templateString(contents string, vars core.PackageTemplateVars, label string) string {
	tmpl := template.Must(template.New(label).Parse(contents))
	var templated bytes.Buffer
	err := tmpl.Execute(&templated, vars)
	if err != nil {
		panic(err)
	}
	return templated.String()
}

func PackageInit(pkgname string) error {
	err := os.Mkdir(".cypkg", 0777)
	if err != nil {
		return fmt.Errorf("error creating .cypkg directory: %v", err)
	}

	err = os.Mkdir(".cypkg/"+pkgname, 0777)
	if err != nil {
		return fmt.Errorf("error creating .cypkg/%v directory: %v", pkgname, err)
	}

	err = os.WriteFile(".cypkg/"+pkgname+"/DEPENDS",
		[]byte("# List package dependencies here, one per line."),
		0777)
	if err != nil {
		return fmt.Errorf("error creating .cypkg/%v/DEPENDS: %v", pkgname, err)
	}

	err = os.WriteFile(".cypkg/"+pkgname+"/CONFLICTS",
		[]byte("# List package conflicts here, one per line."),
		0777)
	if err != nil {
		return fmt.Errorf("error creating .cypkg/%v/CONFLICTS: %v", pkgname, err)
	}
	return nil
}

func (p PackageTarFileProvider) Init(pkgname string) error {
	return PackageInit(pkgname)
}

func (p PackageTarFileProvider) ListPackages() ([]string, error) {
	entries, err := os.ReadDir(".cypkg")
	if err != nil {
		return nil, fmt.Errorf("error reading .cypkg directory: %v", err)
	}

	var packages []string
	for _, entry := range entries {
		if entry.IsDir() {
			packages = append(packages, entry.Name())
		}
	}
	return packages, nil
}

// This function defines the versioning scheme for coyote packages.
// Any git tag that starts with "coyote-" is considered a coyote package version.
// Versions are sorted alphabetically. No other format is imposed.
// TODO: Is this actually a good idea? I find in trying out coyote that I want
// to specify any old git ref as a version, not just tags.
func versionFromTags() (string, error) {
	cmd := exec.Command("git", "tag", "--list", "coyote-*")
	output, err := cmd.Output()
	if err != nil {
		return "", err
	}

	versions := strings.Split(string(output), "\n")
	sort.Strings(versions)

	version := versions[len(versions)-1]
	version = strings.TrimSpace(version)
	version = strings.TrimPrefix(version, "coyote-")
	return version, nil
}

func tagFromVersion(version string) string {
	return "coyote-" + strings.TrimSpace(version)
}

func PackageBuild(pkgname string, outdir string, version string) (string, error) {
	if pkgname == "" {
		return "", fmt.Errorf("package name is required")
	}
	rootTempDir, err := os.MkdirTemp("", "coyote")
	if err != nil {
		return "", fmt.Errorf("error creating temp dir: %v", err)
	}
	defer os.RemoveAll(rootTempDir)

	var cmd *exec.Cmd
	// We support the magic version "HEAD" which means the latest commit, and is only useful for testing
	// This is the only way to build a package from a commit that isn't tagged
	tempDir := rootTempDir + "/" + pkgname
	if version == "HEAD" {
		cmd = exec.Command("git", "clone", ".", tempDir)
	} else {
		// If no version is specified, we build the latest version that's been tagged
		if version == "" {
			version, err = versionFromTags()
			if err != nil {
				return "", fmt.Errorf("error getting latest version: %v", err)
			}
		}
		if version == "" {
			return "", fmt.Errorf("no version found")
		}
		rev := tagFromVersion(version)
		cmd = exec.Command("git", "clone", "--depth", "1", "--branch", rev, ".", tempDir)
	}

	_, err = cmd.CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("error running clone command `%v` %v: %v", cmd, version, err)
	}

	buildFileName := rootTempDir + "/build"
	CopyFileIfExist(tempDir+"/.cypkg/"+pkgname+"/build", buildFileName)
	os.RemoveAll(tempDir + "/.git")
	os.RemoveAll(tempDir + "/.cypkg")

	err = buildMetadata(tempDir, pkgname, version)
	if err != nil {
		return "", err
	}

	filename := pkgname + "-" + version + ".cypkg"

	var resultFilename string
	if fileExists(buildFileName) {
		resultFilename, err = buildWithBuildScript(tempDir, rootTempDir, filename, buildFileName)
	} else {
		resultFilename, err = buildDefaultPackage(tempDir, rootTempDir, filename)
	}
	if err != nil {
		return "", err
	}

	outfile := outdir + "/" + filename

	if !fileExists(outdir) {
		err = os.MkdirAll(outdir, 0777)
		if err != nil {
			return "", fmt.Errorf("error creating output directory: %v", err)
		}
	}

	err = os.Rename(resultFilename, outfile)
	if err != nil {
		return "", fmt.Errorf("error moving the output file: %v", err)
	}

	return outfile, nil
}

func buildWithBuildScript(packageRootDir string, rootTempDir string, filename string, buildScript string) (string, error) {
	cmd := exec.Command("sh", "-c", buildScript)
	cmd.Dir = packageRootDir
	output, err := cmd.CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("error running build script `%v` %v: %v", cmd, buildScript, err)
	}
	tempFilename := rootTempDir + "/" + filename + ".tmp"

	err = os.WriteFile(tempFilename, output, 0644)
	if err != nil {
		return "", fmt.Errorf("error writing build output to file: %v", err)
	}

	// The "./" in this argument sets the member names in the archive. See metadataArchivePrefix.
	tarCmd := exec.Command("tar", "-rf", tempFilename, "-C", packageRootDir, "./"+metadataDirName)
	_, err = tarCmd.Output()
	if err != nil {
		return "", fmt.Errorf("error running tar command `%v`: %v", tarCmd, err)
	}

	targetFilename := rootTempDir + "/" + filename

	err = gzipToFile(tempFilename, targetFilename)
	if err != nil {
		return "", fmt.Errorf("error gzipping file: %v", err)
	}

	return targetFilename, nil
}

func gzipToFile(srcFilename string, destFilename string) error {
	tempFile, err := os.Open(srcFilename)
	if err != nil {
		return fmt.Errorf("error opening temp file: %v", err)
	}
	defer tempFile.Close()

	targetFile, err := os.Create(destFilename)
	if err != nil {
		return fmt.Errorf("error creating target file: %v", err)
	}
	defer targetFile.Close()

	gzipWriter := gzip.NewWriter(targetFile)
	defer gzipWriter.Close()

	_, err = io.Copy(gzipWriter, tempFile)
	if err != nil {
		return fmt.Errorf("error writing gzip output: %v", err)
	}
	return nil
}

func buildDefaultPackage(packageRootDir string, rootTempDir string, filename string) (string, error) {
	// Archiving "." gives every member the "./" prefix, so the metadata is stored under
	// metadataArchivePrefix. Do not change "." to a list of files without keeping that prefix.
	tarCmd := exec.Command("tar", "-czf", "-", "-C", packageRootDir, ".")
	tarOutput, tarErr := tarCmd.Output()
	if tarErr != nil {
		return "", fmt.Errorf("error running tar command `%v`: %v", tarCmd, tarErr)
	}

	targetFilename := rootTempDir + "/" + filename

	err := os.WriteFile(targetFilename, tarOutput, 0644)
	if err != nil {
		return "", fmt.Errorf("error writing tar output to file: %v", err)
	}

	return targetFilename, nil
}

func buildMetadata(tempDir string, pkgname string, version string) error {
	metadataDir := tempDir + "/" + metadataDirName
	os.Mkdir(metadataDir, 0777)

	os.WriteFile(metadataDir+"/DEPENDS", []byte(""), 0777)
	CopyFileIfExist(".cypkg/"+pkgname+"/DEPENDS", metadataDir+"/DEPENDS")
	os.WriteFile(metadataDir+"/CONFLICTS", []byte(""), 0777)
	CopyFileIfExist(".cypkg/"+pkgname+"/CONFLICTS", metadataDir+"/CONFLICTS")

	os.WriteFile(metadataDir+"/VERSION", []byte(version), 0777)
	os.WriteFile(metadataDir+"/NAME", []byte(pkgname), 0777)

	for _, field := range []string{"NAME", "VERSION"} {
		check, err := os.ReadFile(metadataDir + "/" + field)
		if err != nil {
			return fmt.Errorf("error reading back %s from metadata: %v", field, err)
		}
		if string(check) == "" {
			return fmt.Errorf("%s in metadata is empty", field)
		}
	}

	CopyFileIfExist(".cypkg/"+pkgname+"/on-install", metadataDir+"/on-install")
	return nil
}

func (p PackageTarFileProvider) Build(pkgname string, outdir string, version string) (string, error) {
	return PackageBuild(pkgname, outdir, version)
}

func extractFile(header *tar.Header, vars core.PackageTemplateVars, file *tar.Reader) {
	templatedFilename := templateString(header.Name, vars, "Filename "+header.Name)
	mode := header.FileInfo().Mode()

	if header.Typeflag == tar.TypeDir {
		os.MkdirAll(templatedFilename, mode)
	} else if header.Typeflag == tar.TypeSymlink {
		target := header.Linkname
		templatedTarget := templateString(target, vars, "Symlink "+header.Name+" -> "+target)

		os.Symlink(templatedTarget, templatedFilename)
	} else {
		contents, err := io.ReadAll(file)
		if err != nil {
			panic(err)
		}
		// TODO: we shouldn't template binary files, but I don't have a good answer for
		// how we should demarcate them yet
		templatedContents := templateString(string(contents), vars, "Contents "+header.Name)

		os.WriteFile(templatedFilename, []byte(templatedContents), mode)
	}
}

func (p PackageTarFile) Apply(vars core.PackageTemplateVars) {
	tarFile, err := os.Open(p.Filename)
	if err != nil {
		panic(err)
	}
	defer tarFile.Close()
	gzipReader, err := gzip.NewReader(tarFile)
	if err != nil {
		panic(err)
	}
	defer gzipReader.Close()

	files := tar.NewReader(gzipReader)
	for {
		header, err := files.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			panic(err)
		}

		// Skip the metadata, in both the current and the legacy layout. See metadataArchivePrefix.
		if strings.HasPrefix(header.Name, metadataArchivePrefix) ||
			strings.HasPrefix(header.Name, legacyMetadataArchivePrefix) ||
			header.Name == metadataDirName {
			continue
		}

		extractFile(header, vars, files)
	}
}

func (p PackageTarFileProvider) Version() (string, error) {
	return versionFromTags()
}
