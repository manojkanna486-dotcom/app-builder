import { useState, useEffect, useRef } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  Send,
  Code,
  Eye,
  Loader2,
  RefreshCw,
  History,
  Sparkles,
  User,
  Bot,
  Copy,
  Check,
  FileCode,
  FolderOpen,
  ChevronRight,
  ChevronDown,
  Database,
  X,
  CheckCircle,
  AlertCircle,
  ExternalLink,
  Download,
  Rocket,
  Play,
} from "lucide-react";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { ScrollArea } from "../components/ui/scroll-area";
import { Tabs, TabsList, TabsTrigger } from "../components/ui/tabs";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "../components/ui/tooltip";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "../components/ui/dropdown-menu";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "../components/ui/dialog";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { toast } from "sonner";
import axios from "axios";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// File Tree Component
const FileTree = ({ files, selectedFile, onSelectFile }) => {
  const [expandedFolders, setExpandedFolders] = useState(new Set(["components", "hooks", "utils"]));

  // Build tree structure from flat file list
  const buildTree = (files) => {
    const tree = { name: "root", children: {}, files: [] };
    
    files.forEach((file) => {
      const parts = file.path.split("/");
      let current = tree;
      
      for (let i = 0; i < parts.length - 1; i++) {
        const folder = parts[i];
        if (!current.children[folder]) {
          current.children[folder] = { name: folder, children: {}, files: [] };
        }
        current = current.children[folder];
      }
      
      current.files.push({ name: parts[parts.length - 1], path: file.path });
    });
    
    return tree;
  };

  const toggleFolder = (folder) => {
    const newExpanded = new Set(expandedFolders);
    if (newExpanded.has(folder)) {
      newExpanded.delete(folder);
    } else {
      newExpanded.add(folder);
    }
    setExpandedFolders(newExpanded);
  };

  const renderTree = (node, depth = 0) => {
    const folders = Object.values(node.children);
    const sortedFiles = [...node.files].sort((a, b) => a.name.localeCompare(b.name));
    
    return (
      <>
        {folders.map((folder) => (
          <div key={folder.name}>
            <button
              onClick={() => toggleFolder(folder.name)}
              className="w-full flex items-center gap-1 px-2 py-1 hover:bg-muted/50 rounded text-sm text-muted-foreground hover:text-foreground transition-colors"
              style={{ paddingLeft: `${depth * 12 + 8}px` }}
            >
              {expandedFolders.has(folder.name) ? (
                <ChevronDown className="w-3 h-3" />
              ) : (
                <ChevronRight className="w-3 h-3" />
              )}
              <FolderOpen className="w-4 h-4 text-primary/70" />
              <span>{folder.name}</span>
            </button>
            {expandedFolders.has(folder.name) && renderTree(folder, depth + 1)}
          </div>
        ))}
        {sortedFiles.map((file) => (
          <button
            key={file.path}
            onClick={() => onSelectFile(file.path)}
            data-testid={`file-${file.path.replace(/[/.]/g, "-")}`}
            className={`w-full flex items-center gap-2 px-2 py-1 rounded text-sm transition-colors ${
              selectedFile === file.path
                ? "bg-primary/10 text-primary"
                : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"
            }`}
            style={{ paddingLeft: `${depth * 12 + 20}px` }}
          >
            <FileCode className="w-4 h-4" />
            <span className="truncate">{file.name}</span>
          </button>
        ))}
      </>
    );
  };

  const tree = buildTree(files);

  return (
    <div className="py-2">
      {files.length === 0 ? (
        <div className="px-4 py-2 text-sm text-muted-foreground">No files</div>
      ) : (
        renderTree(tree)
      )}
    </div>
  );
};

export default function BuilderPage() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const messagesEndRef = useRef(null);
  const iframeRef = useRef(null);

  const [project, setProject] = useState(null);
  const [messages, setMessages] = useState([]);
  const [versions, setVersions] = useState([]);
  const [prompt, setPrompt] = useState("");
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [generationStatus, setGenerationStatus] = useState("");
  const [streamingCode, setStreamingCode] = useState("");
  const [previewHtml, setPreviewHtml] = useState("");
  const [files, setFiles] = useState([]);
  const [selectedFile, setSelectedFile] = useState("App.jsx");
  const [viewMode, setViewMode] = useState("preview");
  const [copied, setCopied] = useState(false);
  
  // Clarification state
  const [clarificationQuestions, setClarificationQuestions] = useState(null);
  const [clarificationAnswers, setClarificationAnswers] = useState({});
  const [originalPrompt, setOriginalPrompt] = useState("");
  const [analyzing, setAnalyzing] = useState(false);
  
  // Supabase OAuth state
  const [showSupabaseModal, setShowSupabaseModal] = useState(false);
  const [showProjectSelector, setShowProjectSelector] = useState(false);
  const [supabaseProjects, setSupabaseProjects] = useState([]);
  const [supabaseOrgs, setSupabaseOrgs] = useState([]);
  const [selectedSupabaseProject, setSelectedSupabaseProject] = useState("");
  const [supabaseTokenState, setSupabaseTokenState] = useState("");
  const [loadingProjects, setLoadingProjects] = useState(false);
  const [connectingProject, setConnectingProject] = useState(false);
  
  // New project creation state
  const [showNewProjectForm, setShowNewProjectForm] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");
  const [newProjectOrg, setNewProjectOrg] = useState("");
  const [newProjectPassword, setNewProjectPassword] = useState("");
  const [newProjectRegion, setNewProjectRegion] = useState("us-east-1");
  const [creatingNewProject, setCreatingNewProject] = useState(false);

  // Legacy manual connection state (fallback)
  const [supabaseUrl, setSupabaseUrl] = useState("");
  const [supabaseAnonKey, setSupabaseAnonKey] = useState("");
  const [supabaseServiceKey, setSupabaseServiceKey] = useState("");
  const [connectingSupabase, setConnectingSupabase] = useState(false);

  // Vercel deployment state
  const [showVercelModal, setShowVercelModal] = useState(false);
  const [vercelToken, setVercelToken] = useState("");
  const [deploying, setDeploying] = useState(false);
  const [deploymentUrl, setDeploymentUrl] = useState("");

  // Sandbox state
  const [creatingSandbox, setCreatingSandbox] = useState(false);

  // Check for OAuth callback
  useEffect(() => {
    const authState = searchParams.get('supabase_auth');
    if (authState) {
      setSupabaseTokenState(authState);
      setShowProjectSelector(true);
      fetchSupabaseProjects(authState);
      // Clean URL
      window.history.replaceState({}, '', `/builder/${projectId}`);
    }
  }, [searchParams, projectId]);

  useEffect(() => {
    fetchProjectData();
  }, [projectId]);

  useEffect(() => {
    scrollToBottom();
  }, [messages, clarificationQuestions]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  const fetchProjectData = async () => {
    try {
      const [projectRes, messagesRes, previewRes, versionsRes] = await Promise.all([
        axios.get(`${API}/projects/${projectId}`),
        axios.get(`${API}/projects/${projectId}/messages`),
        axios.get(`${API}/projects/${projectId}/preview`),
        axios.get(`${API}/projects/${projectId}/versions`),
      ]);

      setProject(projectRes.data);
      setMessages(messagesRes.data);
      setPreviewHtml(previewRes.data.html);
      setVersions(versionsRes.data);

      // Extract files from latest version
      if (versionsRes.data.length > 0 && versionsRes.data[0].files?.length > 0) {
        setFiles(versionsRes.data[0].files);
        setSelectedFile(versionsRes.data[0].files[0].path);
      }
    } catch (err) {
      toast.error("Failed to load project");
      navigate("/");
    } finally {
      setLoading(false);
    }
  };

  const getSelectedFileContent = () => {
    const file = files.find((f) => f.path === selectedFile);
    return file?.content || "// No file selected";
  };

  // Analyze prompt for clarification
  const analyzePrompt = async (userPrompt) => {
    try {
      setAnalyzing(true);
      console.log("Analyzing prompt:", userPrompt);
      const res = await axios.post(`${API}/projects/${projectId}/analyze`, {
        prompt: userPrompt,
      });
      console.log("Analysis response:", res.data);
      
      if (res.data.needs_clarification && res.data.questions?.length > 0) {
        console.log("Setting clarification questions:", res.data);
        setClarificationQuestions(res.data);
        setOriginalPrompt(userPrompt);
        setClarificationAnswers({});
        return true; // Needs clarification
      }
      console.log("No clarification needed");
      return false; // Proceed with generation
    } catch (err) {
      console.error("Analysis error:", err);
      return false; // On error, proceed without clarification
    } finally {
      setAnalyzing(false);
    }
  };

  // Handle clarification answer selection
  const handleClarificationAnswer = (questionId, answer) => {
    setClarificationAnswers((prev) => ({
      ...prev,
      [questionId]: answer,
    }));
  };

  // Submit clarification answers and generate
  const handleSubmitClarification = async () => {
    // Build enhanced prompt
    const answers = Object.values(clarificationAnswers).filter(Boolean);
    const enhancedPrompt = `${originalPrompt}\n\nAdditional context:\n${answers.map(a => `- ${a}`).join('\n')}`;
    
    setClarificationQuestions(null);
    setClarificationAnswers({});
    setOriginalPrompt("");
    
    // Proceed with generation
    await doGenerate(enhancedPrompt);
  };

  // Skip clarification and generate with original prompt
  const handleSkipClarification = async () => {
    const promptToUse = originalPrompt;
    setClarificationQuestions(null);
    setClarificationAnswers({});
    setOriginalPrompt("");
    
    await doGenerate(promptToUse);
  };

  const handleGenerate = async () => {
    if (!prompt.trim() || generating || analyzing) return;

    const userPrompt = prompt.trim();
    setPrompt("");
    
    // Add user message immediately
    const tempUserMsg = {
      id: `temp-${Date.now()}`,
      role: "user",
      content: userPrompt,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tempUserMsg]);
    
    // Check if clarification is needed (only for new projects without existing code)
    const needsClarification = await analyzePrompt(userPrompt);
    
    if (!needsClarification) {
      await doGenerate(userPrompt);
    }
    // If needs clarification, the UI will show the questions
  };

  const doGenerate = async (userPrompt) => {
    setGenerating(true);
    setGenerationStatus("Starting...");
    setStreamingCode("");
    setViewMode("code"); // Switch to code view to show streaming

    try {
      // Use streaming endpoint
      const response = await fetch(`${API}/projects/${projectId}/generate/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ prompt: userPrompt }),
      });

      if (!response.ok) {
        throw new Error("Generation failed");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const data = JSON.parse(line.slice(6));
              
              if (data.type === "status") {
                setGenerationStatus(data.message);
              } else if (data.type === "code") {
                setStreamingCode((prev) => prev + data.content);
              } else if (data.type === "test_result") {
                // Handle test result events
                if (data.status === "PASS") {
                  toast.success(`🧪 All tests passed! (${data.results?.passed || 0}/${data.results?.total || 0})`);
                } else if (data.retrying) {
                  toast.warning(`🔄 Tests failed (attempt ${data.attempt}). Auto-fixing...`);
                } else if (data.max_attempts_reached) {
                  toast.error(`❌ Tests still failing after ${data.attempt} attempts. Please review the code.`);
                }
              } else if (data.type === "complete") {
                // Generation complete
                if (data.files?.length > 0) {
                  setFiles(data.files);
                  const stillExists = data.files.some((f) => f.path === selectedFile);
                  if (!stillExists) {
                    setSelectedFile(data.files[0].path);
                  }
                }
                
                // Update preview
                const previewRes = await axios.get(`${API}/projects/${projectId}/preview`);
                setPreviewHtml(previewRes.data.html);

                // Refresh messages and versions
                const [messagesRes, versionsRes] = await Promise.all([
                  axios.get(`${API}/projects/${projectId}/messages`),
                  axios.get(`${API}/projects/${projectId}/versions`),
                ]);
                setMessages(messagesRes.data);
                setVersions(versionsRes.data);
                setProject((prev) => ({ ...prev, current_version: data.version }));

                // Show test results summary
                if (data.test_results) {
                  const tr = data.test_results;
                  if (tr.status === "PASS") {
                    toast.success(`✅ All ${tr.total} tests passed!`, { duration: 5000 });
                  } else {
                    toast.error(
                      <div>
                        <strong>⚠️ {tr.failed} of {tr.total} tests failed</strong>
                        <div className="text-sm mt-1">
                          {tr.failed_requirements?.slice(0, 2).map((f, i) => (
                            <div key={i}>• {f.description?.slice(0, 50)}...</div>
                          ))}
                        </div>
                      </div>,
                      { duration: 8000 }
                    );
                  }
                }

                // Show success toast with migration/deployment info
                let successMsg = `Version ${data.version} generated with ${data.files?.length || 0} files!`;
                
                // Show migration status with link to SQL Editor
                if (data.migration) {
                  if (data.migration.status === "ready") {
                    const sqlEditorUrl = data.migration.sql_editor_url;
                    toast.info(
                      <div>
                        🗄️ SQL migrations ready! 
                        <a href={sqlEditorUrl} target="_blank" rel="noopener noreferrer" className="ml-2 underline text-blue-400">
                          Open SQL Editor
                        </a>
                      </div>,
                      { duration: 8000 }
                    );
                  } else if (data.migration.status === "skipped") {
                    // Silently skip - no need to notify
                  }
                }
                
                // Show deployment status
                if (data.deployment) {
                  if (data.deployment.status === "prepared") {
                    toast.info(`⚡ ${data.deployment.total} Edge Function(s) ready for deployment`);
                  }
                }
                
                toast.success(successMsg);
                setViewMode("preview");
              } else if (data.type === "error") {
                throw new Error(data.message);
              }
            } catch (parseErr) {
              // Ignore JSON parse errors for incomplete chunks
            }
          }
        }
      }
    } catch (err) {
      toast.error(err.message || "Generation failed");
    } finally {
      setGenerating(false);
      setGenerationStatus("");
      setStreamingCode("");
    }
  };

  const refreshPreview = () => {
    if (iframeRef.current) {
      iframeRef.current.src = "about:blank";
      setTimeout(() => {
        if (iframeRef.current) {
          iframeRef.current.srcdoc = previewHtml;
        }
      }, 100);
    }
  };

  const copyCode = async () => {
    try {
      await navigator.clipboard.writeText(getSelectedFileContent());
      setCopied(true);
      toast.success("Code copied!");
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      toast.error("Failed to copy");
    }
  };

  const loadVersion = async (version) => {
    try {
      if (version.files?.length > 0) {
        setFiles(version.files);
        setSelectedFile(version.files[0].path);
        // Regenerate preview HTML
        const previewRes = await axios.get(`${API}/projects/${projectId}/preview`);
        setPreviewHtml(previewRes.data.html);
        toast.success(`Loaded version ${version.version_number}`);
      }
    } catch (err) {
      toast.error("Failed to load version");
    }
  };

  // Connect Supabase handler
  const handleConnectSupabase = async () => {
    if (!supabaseUrl.trim() || !supabaseAnonKey.trim()) {
      toast.error("Project URL and Anon Key are required");
      return;
    }

    setConnectingSupabase(true);
    try {
      const res = await axios.post(`${API}/projects/${projectId}/connect-supabase`, {
        url: supabaseUrl.trim(),
        anon_key: supabaseAnonKey.trim(),
        service_role_key: supabaseServiceKey.trim() || null,
      });

      if (res.data.connected) {
        toast.success("Supabase connected successfully!");
        setProject((prev) => ({
          ...prev,
          supabase_connected: true,
          supabase_url: supabaseUrl.trim(),
        }));
        setShowSupabaseModal(false);
        // Reset form
        setSupabaseUrl("");
        setSupabaseAnonKey("");
        setSupabaseServiceKey("");
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to connect Supabase");
    } finally {
      setConnectingSupabase(false);
    }
  };

  // Disconnect Supabase
  const handleDisconnectSupabase = async () => {
    try {
      await axios.post(`${API}/projects/${projectId}/disconnect-supabase`);
      setProject((prev) => ({
        ...prev,
        supabase_connected: false,
        supabase_url: null,
      }));
      toast.success("Supabase disconnected");
    } catch (err) {
      toast.error("Failed to disconnect");
    }
  };

  // Supabase OAuth - Start authentication
  const handleSupabaseOAuth = () => {
    // Redirect to backend OAuth endpoint
    window.location.href = `${API}/auth/supabase/login?project_id=${projectId}`;
  };

  // Fetch Supabase projects after OAuth
  const fetchSupabaseProjects = async (tokenState) => {
    setLoadingProjects(true);
    try {
      const [projectsRes, orgsRes] = await Promise.all([
        axios.get(`${API}/auth/supabase/projects?token_state=${tokenState}`),
        axios.get(`${API}/auth/supabase/organizations?token_state=${tokenState}`)
      ]);
      
      setSupabaseProjects(projectsRes.data.projects || []);
      setSupabaseOrgs(orgsRes.data.organizations || []);
    } catch (err) {
      console.error("Failed to fetch Supabase data:", err);
      toast.error("Failed to fetch Supabase projects");
    } finally {
      setLoadingProjects(false);
    }
  };

  // Connect selected Supabase project
  const handleConnectSelectedProject = async () => {
    if (!selectedSupabaseProject) {
      toast.error("Please select a project");
      return;
    }

    setConnectingProject(true);
    try {
      const res = await axios.post(
        `${API}/auth/supabase/connect/${selectedSupabaseProject}?token_state=${supabaseTokenState}`
      );

      if (res.data.connected) {
        toast.success(`Connected to ${res.data.project_name}!`);
        setProject((prev) => ({
          ...prev,
          supabase_connected: true,
          supabase_url: res.data.supabase_url,
          supabase_project_name: res.data.project_name,
        }));
        setShowProjectSelector(false);
        setSupabaseTokenState("");
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to connect project");
    } finally {
      setConnectingProject(false);
    }
  };

  // Create new Supabase project
  const handleCreateSupabaseProject = async () => {
    if (!newProjectName.trim() || !newProjectOrg || !newProjectPassword.trim()) {
      toast.error("Please fill in all required fields");
      return;
    }

    setCreatingNewProject(true);
    try {
      const res = await axios.post(
        `${API}/auth/supabase/projects/create?token_state=${supabaseTokenState}`,
        {
          name: newProjectName.trim(),
          organization_id: newProjectOrg,
          db_pass: newProjectPassword.trim(),
          region: newProjectRegion
        }
      );

      toast.success("Project created! It may take a few minutes to be ready.");
      
      // Refresh projects list
      await fetchSupabaseProjects(supabaseTokenState);
      
      // Select the new project
      if (res.data.id) {
        setSelectedSupabaseProject(res.data.id);
      }
      
      setShowNewProjectForm(false);
      setNewProjectName("");
      setNewProjectPassword("");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to create project");
    } finally {
      setCreatingNewProject(false);
    }
  };

  // Deploy to Vercel
  const handleDeployToVercel = async () => {
    if (!vercelToken.trim()) {
      toast.error("Vercel token is required");
      return;
    }

    setDeploying(true);
    try {
      const res = await axios.post(`${API}/projects/${projectId}/deploy/vercel`, {
        vercel_token: vercelToken.trim(),
        project_name: project?.name?.toLowerCase().replace(/[^a-z0-9-]/g, '-') || 'my-app'
      });

      if (res.data.success) {
        setDeploymentUrl(res.data.url);
        toast.success("Deployment started! Your app will be live shortly.");
        // Don't close modal - show the URL
      }
    } catch (err) {
      const errorMsg = err.response?.data?.detail || "Deployment failed";
      toast.error(typeof errorMsg === 'string' ? errorMsg : JSON.stringify(errorMsg));
    } finally {
      setDeploying(false);
    }
  };

  // Open in CodeSandbox
  const handleOpenSandbox = async () => {
    setCreatingSandbox(true);
    try {
      const res = await axios.post(`${API}/projects/${projectId}/sandbox`);
      if (res.data.url) {
        window.open(res.data.url, '_blank');
        toast.success("CodeSandbox opened in new tab!");
      }
    } catch (err) {
      toast.error("Failed to create sandbox");
    } finally {
      setCreatingSandbox(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="spinner" />
      </div>
    );
  }

  return (
    <TooltipProvider>
      <div className="split-pane">
        {/* Chat Pane (25%) */}
        <div className="chat-pane bg-background">
          {/* Chat Header */}
          <div className="p-4 border-b border-border flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Button
                variant="ghost"
                size="icon"
                data-testid="back-btn"
                onClick={() => navigate("/")}
              >
                <ArrowLeft className="w-4 h-4" />
              </Button>
              <div>
                <h2 className="font-semibold text-foreground truncate max-w-[180px]">
                  {project?.name}
                </h2>
                {project?.current_version > 0 && (
                  <span className="text-xs text-muted-foreground">
                    v{project.current_version} • {files.length} file{files.length !== 1 ? "s" : ""}
                  </span>
                )}
              </div>
            </div>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" data-testid="versions-btn">
                  <History className="w-4 h-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56 bg-popover border-border">
                <div className="px-2 py-1.5 text-sm font-medium text-muted-foreground">
                  Version History
                </div>
                {versions.length === 0 ? (
                  <div className="px-2 py-4 text-sm text-muted-foreground text-center">
                    No versions yet
                  </div>
                ) : (
                  versions.slice(0, 10).map((v) => (
                    <DropdownMenuItem
                      key={v.id}
                      data-testid={`version-item-${v.version_number}`}
                      onClick={() => loadVersion(v)}
                      className="cursor-pointer"
                    >
                      <div className="flex items-center justify-between w-full">
                        <span>Version {v.version_number}</span>
                        <span
                          className={`text-xs px-1.5 py-0.5 rounded ${
                            v.status === "success"
                              ? "bg-green-500/10 text-green-500"
                              : "bg-destructive/10 text-destructive"
                          }`}
                        >
                          {v.status}
                        </span>
                      </div>
                    </DropdownMenuItem>
                  ))
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>

          {/* Supabase Connection Banner */}
          <div className="px-4 py-2 border-b border-border bg-muted/30">
            {project?.supabase_connected ? (
              <div className="flex items-center justify-between">
                <div className="flex flex-col">
                  <div className="flex items-center gap-2">
                    <CheckCircle className="w-4 h-4 text-green-500" />
                    <span className="text-xs text-green-500 font-medium">Supabase Connected</span>
                  </div>
                  <div className="ml-6 text-xs text-muted-foreground">
                    <span className="font-medium">{project.supabase_project_name || 'Project'}</span>
                    {project.supabase_project_ref && (
                      <span className="text-muted-foreground/60 ml-1">({project.supabase_project_ref})</span>
                    )}
                  </div>
                  <div className="ml-6 text-[10px] text-muted-foreground/50 mt-0.5">
                    All operations will only affect this project
                  </div>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  data-testid="disconnect-supabase-btn"
                  onClick={handleDisconnectSupabase}
                  className="h-6 text-xs text-muted-foreground hover:text-destructive"
                >
                  Disconnect
                </Button>
              </div>
            ) : (
              <Button
                variant="outline"
                size="sm"
                data-testid="connect-supabase-btn"
                onClick={handleSupabaseOAuth}
                className="w-full h-8 text-xs border-dashed border-primary/50 text-primary hover:bg-primary/10"
              >
                <Database className="w-3 h-3 mr-2" />
                Connect Supabase Account
              </Button>
            )}
          </div>

          {/* Messages */}
          <ScrollArea className="message-list">
            <div className="p-4 space-y-4">
              {messages.length === 0 ? (
                <div className="text-center py-8 animate-fade-in">
                  <div className="w-12 h-12 mx-auto mb-3 rounded-xl bg-primary/10 flex items-center justify-center">
                    <Sparkles className="w-6 h-6 text-primary" />
                  </div>
                  <p className="text-sm text-muted-foreground">
                    Describe what you want to build
                  </p>
                </div>
              ) : (
                messages.map((msg, index) => (
                  <div
                    key={msg.id}
                    data-testid={`message-${index}`}
                    className={`flex gap-3 animate-slide-up ${
                      msg.role === "user" ? "flex-row-reverse" : ""
                    }`}
                  >
                    <div
                      className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${
                        msg.role === "user"
                          ? "bg-primary/10"
                          : "bg-card border border-border"
                      }`}
                    >
                      {msg.role === "user" ? (
                        <User className="w-4 h-4 text-primary" />
                      ) : (
                        <Bot className="w-4 h-4 text-muted-foreground" />
                      )}
                    </div>
                    <div
                      className={`px-4 py-3 rounded-2xl max-w-[85%] ${
                        msg.role === "user"
                          ? "chat-bubble-user"
                          : "chat-bubble-ai"
                      }`}
                    >
                      <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
                    </div>
                  </div>
                ))
              )}
              {generating && (
                <div className="flex gap-3 animate-slide-up">
                  <div className="w-8 h-8 rounded-lg bg-card border border-border flex items-center justify-center">
                    <Bot className="w-4 h-4 text-muted-foreground" />
                  </div>
                  <div className="chat-bubble-ai px-4 py-3 min-w-[200px]">
                    <div className="flex items-center gap-2 mb-2">
                      <Loader2 className="w-4 h-4 animate-spin text-primary" />
                      <span className="text-sm font-medium text-foreground">
                        {generationStatus || "Generating..."}
                      </span>
                    </div>
                    {streamingCode && (
                      <div className="mt-2 p-2 bg-background/50 rounded text-xs font-mono text-muted-foreground max-h-24 overflow-hidden">
                        <code className="whitespace-pre-wrap">
                          {streamingCode.slice(-200)}
                        </code>
                      </div>
                    )}
                  </div>
                </div>
              )}
              
              {/* Analyzing indicator */}
              {analyzing && (
                <div className="flex gap-3 animate-slide-up">
                  <div className="w-8 h-8 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center">
                    <Sparkles className="w-4 h-4 text-primary" />
                  </div>
                  <div className="chat-bubble-ai px-4 py-3">
                    <div className="flex items-center gap-2">
                      <Loader2 className="w-4 h-4 animate-spin text-primary" />
                      <span className="text-sm text-muted-foreground">
                        Analyzing your request...
                      </span>
                    </div>
                  </div>
                </div>
              )}
              
              {/* Clarification Questions UI */}
              {clarificationQuestions && clarificationQuestions.needs_clarification && (
                <div className="flex gap-3 animate-slide-up">
                  <div className="w-8 h-8 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-center justify-center shrink-0">
                    <Sparkles className="w-4 h-4 text-amber-500" />
                  </div>
                  <div className="flex-1 max-w-[90%]">
                    <div className="bg-card border border-border rounded-2xl p-4 space-y-4">
                      {/* Project Summary */}
                      {clarificationQuestions.project_summary && (
                        <div className="pb-3 border-b border-border">
                          <p className="text-sm font-medium text-foreground mb-1">
                            📋 I understand you want to build:
                          </p>
                          <p className="text-sm text-muted-foreground">
                            {clarificationQuestions.project_summary}
                          </p>
                        </div>
                      )}
                      
                      {/* Requirements Preview */}
                      {clarificationQuestions.requirements && clarificationQuestions.requirements.length > 0 && (
                        <div className="pb-3 border-b border-border">
                          <p className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wider">
                            Extracted Requirements ({clarificationQuestions.requirements.length})
                          </p>
                          <div className="space-y-1 max-h-32 overflow-y-auto">
                            {clarificationQuestions.requirements.slice(0, 5).map((req, idx) => (
                              <div key={req.id || idx} className="flex items-start gap-2 text-xs">
                                <span className={`shrink-0 ${
                                  req.priority === 'must-have' ? 'text-red-500' : 
                                  req.priority === 'should-have' ? 'text-yellow-500' : 'text-green-500'
                                }`}>●</span>
                                <span className="text-muted-foreground">{req.description}</span>
                              </div>
                            ))}
                            {clarificationQuestions.requirements.length > 5 && (
                              <p className="text-xs text-muted-foreground italic">
                                +{clarificationQuestions.requirements.length - 5} more requirements...
                              </p>
                            )}
                          </div>
                        </div>
                      )}

                      <div>
                        <p className="text-sm font-medium text-foreground mb-1">
                          🎨 A few questions to perfect your app:
                        </p>
                        {clarificationQuestions.context && (
                          <p className="text-xs text-muted-foreground">
                            {clarificationQuestions.context}
                          </p>
                        )}
                      </div>
                      
                      <div className="space-y-3">
                        {clarificationQuestions.questions.map((q, idx) => (
                          <div key={q.id || idx} className="space-y-2">
                            <div>
                              <p className="text-sm text-foreground">{q.question}</p>
                              {q.context && (
                                <p className="text-xs text-muted-foreground mt-0.5">{q.context}</p>
                              )}
                            </div>
                            {q.options ? (
                              <div className="flex flex-wrap gap-2">
                                {q.options.map((opt, optIdx) => (
                                  <button
                                    key={optIdx}
                                    onClick={() => handleClarificationAnswer(q.id || `q${idx}`, opt)}
                                    className={`px-3 py-1.5 text-xs rounded-full border transition-all ${
                                      clarificationAnswers[q.id || `q${idx}`] === opt
                                        ? "bg-primary text-primary-foreground border-primary"
                                        : "bg-background border-border hover:border-primary/50 text-muted-foreground hover:text-foreground"
                                    }`}
                                  >
                                    {opt}
                                  </button>
                                ))}
                              </div>
                            ) : (
                              <input
                                type="text"
                                placeholder="Type your answer..."
                                className="w-full px-3 py-2 text-sm bg-background border border-border rounded-lg focus:outline-none focus:ring-1 focus:ring-primary"
                                onChange={(e) => handleClarificationAnswer(q.id || `q${idx}`, e.target.value)}
                                value={clarificationAnswers[q.id || `q${idx}`] || ""}
                              />
                            )}
                            {q.default && !clarificationAnswers[q.id || `q${idx}`] && (
                              <p className="text-xs text-muted-foreground">
                                Default: {q.default}
                              </p>
                            )}
                          </div>
                        ))}
                      </div>
                      
                      {/* Assumptions */}
                      {clarificationQuestions.assumptions && clarificationQuestions.assumptions.length > 0 && (
                        <div className="pt-2 border-t border-border">
                          <p className="text-xs font-medium text-muted-foreground mb-1">
                            I'll also assume:
                          </p>
                          <ul className="text-xs text-muted-foreground space-y-0.5">
                            {clarificationQuestions.assumptions.slice(0, 3).map((a, i) => (
                              <li key={i}>• {a}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      
                      <div className="flex gap-2 pt-2">
                        <Button
                          size="sm"
                          onClick={handleSubmitClarification}
                          className="flex-1"
                        >
                          ✨ Generate with these preferences
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={handleSkipClarification}
                        >
                          Skip & Use Defaults
                        </Button>
                      </div>
                    </div>
                  </div>
                </div>
              )}
              
              <div ref={messagesEndRef} />
            </div>
          </ScrollArea>

          {/* Input Area */}
          <div className="chat-input-area">
            {clarificationQuestions ? (
              <div className="text-center py-2 text-xs text-muted-foreground">
                Please answer the questions above or skip to generate
              </div>
            ) : (
              <>
                <div className="relative">
                  <Textarea
                    data-testid="prompt-input"
                    placeholder={analyzing ? "Analyzing..." : "Describe what you want to build..."}
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        handleGenerate();
                      }
                    }}
                    disabled={generating || analyzing}
                    className="min-h-[80px] resize-none pr-12 bg-card border-border focus:ring-primary"
                  />
                  <Button
                    data-testid="send-btn"
                    size="icon"
                    onClick={handleGenerate}
                    disabled={!prompt.trim() || generating || analyzing}
                    className="absolute right-2 bottom-2 h-8 w-8 glow-blue-hover"
                  >
                    {generating || analyzing ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Send className="w-4 h-4" />
                    )}
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground mt-2">
                  Press Enter to send, Shift+Enter for new line
                </p>
              </>
            )}
          </div>
        </div>

        {/* Preview Pane (75%) */}
        <div className="preview-pane bg-muted/30">
          {/* Preview Header */}
          <div className="p-3 border-b border-border flex items-center justify-between bg-background">
            <Tabs value={viewMode} onValueChange={setViewMode}>
              <TabsList className="bg-muted/50">
                <TabsTrigger value="preview" data-testid="preview-tab">
                  <Eye className="w-4 h-4 mr-2" />
                  Preview
                </TabsTrigger>
                <TabsTrigger value="code" data-testid="code-tab">
                  <Code className="w-4 h-4 mr-2" />
                  Code
                </TabsTrigger>
              </TabsList>
            </Tabs>
            <div className="flex items-center gap-2">
              {viewMode === "code" && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      data-testid="copy-code-btn"
                      onClick={copyCode}
                    >
                      {copied ? (
                        <Check className="w-4 h-4 text-green-500" />
                      ) : (
                        <Copy className="w-4 h-4" />
                      )}
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>Copy code</TooltipContent>
                </Tooltip>
              )}
              {viewMode === "preview" && (
                <>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="default"
                        size="sm"
                        data-testid="deploy-vercel-btn"
                        onClick={() => setShowVercelModal(true)}
                        className="bg-black hover:bg-gray-800 text-white gap-1 h-8"
                      >
                        <Rocket className="w-3 h-3" />
                        Deploy
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>Deploy to Vercel</TooltipContent>
                  </Tooltip>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="outline"
                        size="sm"
                        data-testid="sandbox-btn"
                        onClick={handleOpenSandbox}
                        disabled={creatingSandbox}
                        className="gap-1 h-8"
                      >
                        {creatingSandbox ? (
                          <Loader2 className="w-3 h-3 animate-spin" />
                        ) : (
                          <Play className="w-3 h-3" />
                        )}
                        Sandbox
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>Open in CodeSandbox (editable)</TooltipContent>
                  </Tooltip>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        data-testid="download-zip-btn"
                        onClick={() => {
                          window.location.href = `${API}/projects/${projectId}/export`;
                          toast.success("Downloading ZIP...");
                        }}
                      >
                        <Download className="w-4 h-4" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>Download ZIP</TooltipContent>
                  </Tooltip>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        data-testid="open-preview-btn"
                        onClick={() => window.open(`${API}/projects/${projectId}/preview/live`, '_blank')}
                      >
                        <ExternalLink className="w-4 h-4" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>Open in new tab</TooltipContent>
                  </Tooltip>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        data-testid="refresh-preview-btn"
                        onClick={refreshPreview}
                      >
                        <RefreshCw className="w-4 h-4" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>Refresh preview</TooltipContent>
                  </Tooltip>
                </>
              )}
            </div>
          </div>

          {/* Preview Content */}
          <div className="flex-1 overflow-hidden p-4">
            {viewMode === "preview" ? (
              <div className="h-full rounded-lg overflow-hidden border border-border shadow-xl bg-white">
                {/* Browser Chrome */}
                <div className="browser-chrome">
                  <div className="browser-dots">
                    <div className="browser-dot browser-dot-red" />
                    <div className="browser-dot browser-dot-yellow" />
                    <div className="browser-dot browser-dot-green" />
                  </div>
                  <div className="browser-address flex items-center gap-2">
                    <span>localhost:3000</span>
                    <button 
                      onClick={() => {
                        navigator.clipboard.writeText(`${API}/projects/${projectId}/preview/live`);
                        toast.success("Preview URL copied!");
                      }}
                      className="text-xs text-blue-400 hover:text-blue-300 underline"
                    >
                      Copy URL
                    </button>
                  </div>
                </div>
                {/* Iframe */}
                <iframe
                  ref={iframeRef}
                  data-testid="preview-iframe"
                  title="App Preview"
                  srcDoc={previewHtml}
                  className="preview-iframe"
                  sandbox="allow-scripts allow-same-origin allow-modals allow-forms allow-popups"
                />
              </div>
            ) : (
              <div className="h-full flex rounded-lg overflow-hidden border border-border">
                {/* File Tree Sidebar */}
                <div className="w-48 bg-card border-r border-border flex-shrink-0">
                  <div className="p-2 border-b border-border">
                    <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                      Files
                    </span>
                  </div>
                  <ScrollArea className="h-[calc(100%-36px)]">
                    <FileTree
                      files={files}
                      selectedFile={selectedFile}
                      onSelectFile={setSelectedFile}
                    />
                  </ScrollArea>
                </div>
                {/* Code View */}
                <div className="flex-1 overflow-hidden">
                  <div className="h-8 px-4 bg-muted/30 border-b border-border flex items-center">
                    <span className="text-xs text-muted-foreground font-mono">
                      {selectedFile}
                    </span>
                    {generating && (
                      <span className="ml-2 text-xs text-primary flex items-center gap-1">
                        <Loader2 className="w-3 h-3 animate-spin" />
                        {generationStatus}
                      </span>
                    )}
                  </div>
                  <ScrollArea className="h-[calc(100%-32px)]">
                    <pre className="code-view">
                      <code>
                        {generating && streamingCode 
                          ? streamingCode 
                          : getSelectedFileContent()}
                      </code>
                    </pre>
                  </ScrollArea>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Supabase Connection Modal */}
      <Dialog open={showSupabaseModal} onOpenChange={setShowSupabaseModal}>
        <DialogContent className="sm:max-w-[500px] bg-background border-border">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Database className="w-5 h-5 text-primary" />
              Connect Supabase
            </DialogTitle>
            <DialogDescription>
              Connect your Supabase project to generate full-stack applications with a real database and Edge Functions backend.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="supabase-url">Project URL *</Label>
              <Input
                id="supabase-url"
                data-testid="supabase-url-input"
                placeholder="https://your-project.supabase.co"
                value={supabaseUrl}
                onChange={(e) => setSupabaseUrl(e.target.value)}
                className="bg-card border-border"
              />
              <p className="text-xs text-muted-foreground">
                Find this in Project Settings → API
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="supabase-anon-key">Anon / Public Key *</Label>
              <Input
                id="supabase-anon-key"
                data-testid="supabase-anon-key-input"
                placeholder="eyJhbGciOiJIUzI1NiIsInR..."
                value={supabaseAnonKey}
                onChange={(e) => setSupabaseAnonKey(e.target.value)}
                className="bg-card border-border font-mono text-xs"
              />
              <p className="text-xs text-muted-foreground">
                Safe for frontend use
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="supabase-service-key">
                Service Role Key <span className="text-muted-foreground">(optional)</span>
              </Label>
              <Input
                id="supabase-service-key"
                data-testid="supabase-service-key-input"
                type="password"
                placeholder="eyJhbGciOiJIUzI1NiIsInR..."
                value={supabaseServiceKey}
                onChange={(e) => setSupabaseServiceKey(e.target.value)}
                className="bg-card border-border font-mono text-xs"
              />
              <p className="text-xs text-muted-foreground">
                Required for admin operations (keep secret)
              </p>
            </div>

            <div className="bg-amber-500/10 border border-amber-500/20 rounded-lg p-3">
              <div className="flex items-start gap-2">
                <AlertCircle className="w-4 h-4 text-amber-500 mt-0.5" />
                <div className="text-xs text-amber-200">
                  <p className="font-medium">How to get these credentials:</p>
                  <ol className="list-decimal ml-4 mt-1 space-y-1 text-amber-200/80">
                    <li>Go to your Supabase Dashboard</li>
                    <li>Click Project Settings → API</li>
                    <li>Copy the Project URL and keys</li>
                  </ol>
                </div>
              </div>
            </div>
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowSupabaseModal(false)}
              disabled={connectingSupabase}
            >
              Cancel
            </Button>
            <Button
              data-testid="connect-supabase-submit-btn"
              onClick={handleConnectSupabase}
              disabled={connectingSupabase || !supabaseUrl.trim() || !supabaseAnonKey.trim()}
            >
              {connectingSupabase ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Connecting...
                </>
              ) : (
                <>
                  <Database className="w-4 h-4 mr-2" />
                  Connect
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Supabase Project Selector Modal (OAuth) */}
      <Dialog open={showProjectSelector} onOpenChange={setShowProjectSelector}>
        <DialogContent className="sm:max-w-[600px] bg-background border-border">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Database className="w-5 h-5 text-green-500" />
              Select Supabase Project
            </DialogTitle>
            <DialogDescription>
              Choose an existing project or create a new one to connect with your app.
            </DialogDescription>
          </DialogHeader>

          {loadingProjects ? (
            <div className="py-8 text-center">
              <Loader2 className="w-8 h-8 animate-spin mx-auto text-primary" />
              <p className="text-sm text-muted-foreground mt-2">Loading your projects...</p>
            </div>
          ) : showNewProjectForm ? (
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label>Project Name *</Label>
                <Input
                  placeholder="My Awesome App"
                  value={newProjectName}
                  onChange={(e) => setNewProjectName(e.target.value)}
                />
              </div>

              <div className="space-y-2">
                <Label>Organization *</Label>
                <select
                  value={newProjectOrg}
                  onChange={(e) => setNewProjectOrg(e.target.value)}
                  className="w-full h-10 px-3 rounded-md border border-border bg-card text-sm"
                >
                  <option value="">Select organization...</option>
                  {supabaseOrgs.map((org) => (
                    <option key={org.id} value={org.id}>
                      {org.name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-2">
                <Label>Database Password *</Label>
                <Input
                  type="password"
                  placeholder="Strong password..."
                  value={newProjectPassword}
                  onChange={(e) => setNewProjectPassword(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  Min 6 characters. You'll need this to connect directly to the database.
                </p>
              </div>

              <div className="space-y-2">
                <Label>Region</Label>
                <select
                  value={newProjectRegion}
                  onChange={(e) => setNewProjectRegion(e.target.value)}
                  className="w-full h-10 px-3 rounded-md border border-border bg-card text-sm"
                >
                  <option value="us-east-1">US East (N. Virginia)</option>
                  <option value="us-west-1">US West (N. California)</option>
                  <option value="eu-west-1">EU (Ireland)</option>
                  <option value="ap-southeast-1">Asia Pacific (Singapore)</option>
                  <option value="ap-south-1">Asia Pacific (Mumbai)</option>
                </select>
              </div>

              <div className="flex gap-2 pt-2">
                <Button
                  variant="outline"
                  onClick={() => setShowNewProjectForm(false)}
                  disabled={creatingNewProject}
                  className="flex-1"
                >
                  Back
                </Button>
                <Button
                  onClick={handleCreateSupabaseProject}
                  disabled={creatingNewProject || !newProjectName || !newProjectOrg || !newProjectPassword}
                  className="flex-1"
                >
                  {creatingNewProject ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      Creating...
                    </>
                  ) : (
                    "Create Project"
                  )}
                </Button>
              </div>
            </div>
          ) : (
            <div className="space-y-4 py-4">
              {supabaseProjects.length > 0 ? (
                <>
                  <div className="space-y-2">
                    <Label>Your Projects</Label>
                    <div className="grid gap-2 max-h-[300px] overflow-y-auto">
                      {supabaseProjects.map((proj) => (
                        <div
                          key={proj.id}
                          onClick={() => setSelectedSupabaseProject(proj.id)}
                          className={`p-3 rounded-lg border cursor-pointer transition-colors ${
                            selectedSupabaseProject === proj.id
                              ? "border-primary bg-primary/10"
                              : "border-border hover:border-primary/50"
                          }`}
                        >
                          <div className="flex items-center justify-between">
                            <div>
                              <p className="font-medium">{proj.name}</p>
                              <p className="text-xs text-muted-foreground">
                                {proj.region} • {proj.status}
                              </p>
                            </div>
                            {selectedSupabaseProject === proj.id && (
                              <CheckCircle className="w-5 h-5 text-primary" />
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      onClick={() => setShowNewProjectForm(true)}
                      className="flex-1"
                    >
                      Create New Project
                    </Button>
                    <Button
                      onClick={handleConnectSelectedProject}
                      disabled={!selectedSupabaseProject || connectingProject}
                      className="flex-1"
                    >
                      {connectingProject ? (
                        <>
                          <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                          Connecting...
                        </>
                      ) : (
                        "Connect Selected"
                      )}
                    </Button>
                  </div>
                </>
              ) : (
                <div className="text-center py-8">
                  <Database className="w-12 h-12 mx-auto text-muted-foreground mb-3" />
                  <p className="text-muted-foreground mb-4">No projects found</p>
                  <Button onClick={() => setShowNewProjectForm(true)}>
                    Create Your First Project
                  </Button>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Vercel Deployment Modal */}
      <Dialog open={showVercelModal} onOpenChange={setShowVercelModal}>
        <DialogContent className="sm:max-w-[500px] bg-background border-border">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Rocket className="w-5 h-5" />
              Deploy to Vercel
            </DialogTitle>
            <DialogDescription>
              Deploy your app directly to Vercel with one click. Your app will be live in seconds.
            </DialogDescription>
          </DialogHeader>

          {deploymentUrl ? (
            <div className="py-6">
              <div className="bg-green-500/10 border border-green-500/20 rounded-lg p-4 text-center">
                <CheckCircle className="w-12 h-12 text-green-500 mx-auto mb-3" />
                <h3 className="font-semibold text-green-400 mb-2">Deployment Started!</h3>
                <p className="text-sm text-muted-foreground mb-4">
                  Your app is being deployed. It will be live at:
                </p>
                <a
                  href={deploymentUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 text-blue-400 hover:text-blue-300 underline break-all"
                >
                  {deploymentUrl}
                  <ExternalLink className="w-4 h-4 flex-shrink-0" />
                </a>
                <p className="text-xs text-muted-foreground mt-4">
                  Note: First deployment may take 1-2 minutes to build.
                </p>
              </div>
              <div className="mt-4 flex justify-center">
                <Button
                  variant="outline"
                  onClick={() => {
                    setShowVercelModal(false);
                    setDeploymentUrl("");
                    setVercelToken("");
                  }}
                >
                  Close
                </Button>
              </div>
            </div>
          ) : (
            <>
              <div className="space-y-4 py-4">
                <div className="space-y-2">
                  <Label htmlFor="vercel-token">Vercel Access Token *</Label>
                  <Input
                    id="vercel-token"
                    data-testid="vercel-token-input"
                    type="password"
                    placeholder="Enter your Vercel token..."
                    value={vercelToken}
                    onChange={(e) => setVercelToken(e.target.value)}
                    className="bg-card border-border font-mono text-xs"
                  />
                </div>

                <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-3">
                  <div className="flex items-start gap-2">
                    <AlertCircle className="w-4 h-4 text-blue-400 mt-0.5" />
                    <div className="text-xs text-blue-200">
                      <p className="font-medium mb-1">How to get your Vercel token:</p>
                      <ol className="list-decimal ml-4 space-y-1 text-blue-200/80">
                        <li>Go to <a href="https://vercel.com/account/tokens" target="_blank" rel="noopener noreferrer" className="underline">vercel.com/account/tokens</a></li>
                        <li>Click "Create" to generate a new token</li>
                        <li>Give it a name (e.g., "App Builder")</li>
                        <li>Copy and paste the token here</li>
                      </ol>
                      <p className="mt-2 text-blue-300">Your token is stored locally and never saved on our servers.</p>
                    </div>
                  </div>
                </div>
              </div>

              <DialogFooter>
                <Button
                  variant="outline"
                  onClick={() => setShowVercelModal(false)}
                  disabled={deploying}
                >
                  Cancel
                </Button>
                <Button
                  data-testid="deploy-vercel-submit-btn"
                  onClick={handleDeployToVercel}
                  disabled={deploying || !vercelToken.trim()}
                  className="bg-black hover:bg-gray-800"
                >
                  {deploying ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      Deploying...
                    </>
                  ) : (
                    <>
                      <Rocket className="w-4 h-4 mr-2" />
                      Deploy Now
                    </>
                  )}
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </TooltipProvider>
  );
}
