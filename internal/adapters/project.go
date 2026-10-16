package adapters

import (
	"fmt"
	"os"
	"strings"

	core "github.com/nhsdigital/coyote/internal/core"
)

// The Project struct represents the local checked out project that we are working with.
type Project struct {
	// The path is the root of the repo, where the .coyote directory is located.
	Path string
}

type ProjectProvider struct{}

func NewProjectProvider() core.IProvideProjects {
	return ProjectProvider{}
}

// NewProject creates a new Project struct.
func (prod ProjectProvider) NewProject(path string, name string) core.Project {
	proj := Project{Path: path}
	proj.Init(name)
	return &proj
}

// MaybeProject returns a Project struct if the current working directory is a project, and nil otherwise.
func (prod ProjectProvider) MaybeProject(path string) core.Project {
	_, err := os.Stat(path + "/.coyote")
	if err != nil {
		return nil
	}
	return &Project{Path: path}
}

func (p *Project) GetPath() string {
	return p.Path
}

func (p *Project) GetName() string {
	name, err := os.ReadFile(p.Path + "/.coyote/project-name")
	if err != nil {
		panic(err) // This is a holding pattern, I don't think it should happen but need to check
	}
	return strings.TrimSpace(string(name))
}

func (p *Project) RecordInstalledPackage(pkg core.PackageFile) error {
	installedFile := NewInstalledFile(p.Path + "/.coyote/installed")

	name := pkg.ReadMetadata("NAME")
	version := pkg.ReadMetadata("VERSION")

	var missing []string

	if name == "" {
		missing = append(missing, "NAME")
	}
	if version == "" {
		missing = append(missing, "VERSION")
	}
	if len(missing) > 0 {
		return fmt.Errorf("package file %v is missing required fields: %s", pkg, strings.Join(missing, ", "))
	}
	return installedFile.Record(name, version)
}

func (p *Project) ReadInstalledPackages() ([][]string, error) {
	installedFile := NewInstalledFile(p.Path + "/.coyote/installed")
	return installedFile.Read()
}

func (p *Project) Init(name string) error {
	err := os.MkdirAll(p.Path+"/.coyote", 0755)
	if err != nil {
		return err
	}
	return os.WriteFile(p.Path+"/.coyote/project-name", []byte(name), 0644)
}
