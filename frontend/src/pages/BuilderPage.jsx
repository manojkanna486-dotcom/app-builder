import { useState, useEffect, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
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
  
  // Supabase connection state
  const [showSupabaseModal, setShowSupabaseModal] = useState(false);
  const [supabaseUrl, setSupabaseUrl] = useState("");
  const [supabaseAnonKey, setSupabaseAnonKey] = useState("");
  const [supabaseServiceKey, setSupabaseServiceKey] = useState("");
  const [connectingSupabase, setConnectingSupabase] = useState(false);

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

                toast.success(`Version ${data.version} generated with ${data.files?.length || 0} files!`);
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
                <div className="flex items-center gap-2">
                  <CheckCircle className="w-4 h-4 text-green-500" />
                  <span className="text-xs text-green-500 font-medium">Supabase Connected</span>
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
                onClick={() => setShowSupabaseModal(true)}
                className="w-full h-8 text-xs border-dashed border-primary/50 text-primary hover:bg-primary/10"
              >
                <Database className="w-3 h-3 mr-2" />
                Connect Supabase for Full-Stack Apps
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
                      <div>
                        <p className="text-sm font-medium text-foreground mb-1">
                          Let me help you build the best app! 🎨
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
                            <p className="text-sm text-foreground">{q.question}</p>
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
                          </div>
                        ))}
                      </div>
                      
                      <div className="flex gap-2 pt-2">
                        <Button
                          size="sm"
                          onClick={handleSubmitClarification}
                          disabled={Object.keys(clarificationAnswers).length === 0}
                          className="flex-1"
                        >
                          Generate with these preferences
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={handleSkipClarification}
                        >
                          Skip & Generate
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
    </TooltipProvider>
  );
}
