import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Plus, Folder, Trash2, Clock, ArrowRight, Sparkles } from "lucide-react";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Card, CardContent } from "../components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "../components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "../components/ui/alert-dialog";
import { toast } from "sonner";
import axios from "axios";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export default function HomePage() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [projectToDelete, setProjectToDelete] = useState(null);
  const [newProjectName, setNewProjectName] = useState("");
  const [newProjectDesc, setNewProjectDesc] = useState("");
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    fetchProjects();
  }, []);

  const fetchProjects = async () => {
    try {
      const res = await axios.get(`${API}/projects`);
      setProjects(res.data);
    } catch (err) {
      toast.error("Failed to load projects");
    } finally {
      setLoading(false);
    }
  };

  const createProject = async () => {
    if (!newProjectName.trim()) {
      toast.error("Project name is required");
      return;
    }

    setCreating(true);
    try {
      const res = await axios.post(`${API}/projects`, {
        name: newProjectName,
        description: newProjectDesc,
      });
      setProjects([res.data, ...projects]);
      setCreateDialogOpen(false);
      setNewProjectName("");
      setNewProjectDesc("");
      toast.success("Project created!");
      navigate(`/builder/${res.data.id}`);
    } catch (err) {
      toast.error("Failed to create project");
    } finally {
      setCreating(false);
    }
  };

  const deleteProject = async () => {
    if (!projectToDelete) return;

    try {
      await axios.delete(`${API}/projects/${projectToDelete.id}`);
      setProjects(projects.filter((p) => p.id !== projectToDelete.id));
      toast.success("Project deleted");
    } catch (err) {
      toast.error("Failed to delete project");
    } finally {
      setDeleteDialogOpen(false);
      setProjectToDelete(null);
    }
  };

  const formatDate = (dateStr) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  };

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b border-border">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
              <Sparkles className="w-5 h-5 text-primary" />
            </div>
            <div>
              <h1 className="text-xl font-semibold text-foreground">Astra AI</h1>
              <p className="text-sm text-muted-foreground">Build full-stack apps with AI</p>
            </div>
          </div>
          <Button
            data-testid="create-project-btn"
            onClick={() => setCreateDialogOpen(true)}
            className="glow-blue-hover"
          >
            <Plus className="w-4 h-4 mr-2" />
            New Project
          </Button>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-6 py-8">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <div className="spinner" />
          </div>
        ) : projects.length === 0 ? (
          /* Empty State */
          <div className="text-center py-20 animate-fade-in">
            <div className="w-20 h-20 mx-auto mb-6 rounded-2xl bg-card flex items-center justify-center border border-border">
              <Folder className="w-10 h-10 text-muted-foreground" />
            </div>
            <h2 className="text-2xl font-semibold text-foreground mb-2">No projects yet</h2>
            <p className="text-muted-foreground mb-6 max-w-md mx-auto">
              Create your first project and start building React applications with natural language.
            </p>
            <Button
              data-testid="create-first-project-btn"
              onClick={() => setCreateDialogOpen(true)}
              size="lg"
              className="glow-blue"
            >
              <Plus className="w-5 h-5 mr-2" />
              Create Your First Project
            </Button>
          </div>
        ) : (
          /* Project Grid */
          <div>
            <h2 className="text-lg font-medium text-foreground mb-6">Your Projects</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {projects.map((project, index) => (
                <Card
                  key={project.id}
                  data-testid={`project-card-${index}`}
                  className="project-card bg-card border-border hover:border-primary/50 cursor-pointer group"
                  onClick={() => navigate(`/builder/${project.id}`)}
                >
                  <CardContent className="p-6">
                    <div className="flex items-start justify-between mb-4">
                      <div className="w-12 h-12 rounded-xl bg-primary/10 flex items-center justify-center">
                        <Folder className="w-6 h-6 text-primary" />
                      </div>
                      <Button
                        variant="ghost"
                        size="icon"
                        data-testid={`delete-project-btn-${index}`}
                        className="opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-destructive"
                        onClick={(e) => {
                          e.stopPropagation();
                          setProjectToDelete(project);
                          setDeleteDialogOpen(true);
                        }}
                      >
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    </div>
                    <h3 className="text-lg font-semibold text-foreground mb-1 truncate">
                      {project.name}
                    </h3>
                    <p className="text-sm text-muted-foreground mb-4 line-clamp-2 min-h-[40px]">
                      {project.description || project.summary || "No description"}
                    </p>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center text-xs text-muted-foreground">
                        <Clock className="w-3 h-3 mr-1" />
                        {formatDate(project.updated_at || project.created_at)}
                      </div>
                      <div className="flex items-center text-xs text-primary opacity-0 group-hover:opacity-100 transition-opacity">
                        Open <ArrowRight className="w-3 h-3 ml-1" />
                      </div>
                    </div>
                    {project.current_version > 0 && (
                      <div className="mt-3 pt-3 border-t border-border">
                        <span className="text-xs px-2 py-1 rounded-full bg-primary/10 text-primary">
                          v{project.current_version}
                        </span>
                      </div>
                    )}
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        )}
      </main>

      {/* Create Project Dialog */}
      <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
        <DialogContent className="bg-card border-border">
          <DialogHeader>
            <DialogTitle>Create New Project</DialogTitle>
            <DialogDescription>
              Give your project a name and optional description.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div>
              <label className="text-sm font-medium text-foreground mb-2 block">
                Project Name
              </label>
              <Input
                data-testid="project-name-input"
                placeholder="My Awesome App"
                value={newProjectName}
                onChange={(e) => setNewProjectName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && createProject()}
                className="bg-background border-border"
              />
            </div>
            <div>
              <label className="text-sm font-medium text-foreground mb-2 block">
                Description (optional)
              </label>
              <Input
                data-testid="project-desc-input"
                placeholder="A brief description of your project"
                value={newProjectDesc}
                onChange={(e) => setNewProjectDesc(e.target.value)}
                className="bg-background border-border"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              data-testid="confirm-create-btn"
              onClick={createProject}
              disabled={creating}
              className="glow-blue-hover"
            >
              {creating ? (
                <>
                  <div className="spinner mr-2" /> Creating...
                </>
              ) : (
                <>
                  <Plus className="w-4 h-4 mr-2" /> Create Project
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent className="bg-card border-border">
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Project?</AlertDialogTitle>
            <AlertDialogDescription>
              This will permanently delete "{projectToDelete?.name}" and all its versions.
              This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              data-testid="confirm-delete-btn"
              onClick={deleteProject}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
