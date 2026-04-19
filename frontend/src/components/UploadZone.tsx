import { useState, useCallback, useRef } from 'react';
import { Upload, Link, FileText, Globe, Loader2 } from 'lucide-react';

interface UploadZoneProps {
  onFileUpload: (file: File) => void;
  onURLAnalyze: (url: string) => void;
  isLoading: boolean;
}

export function UploadZone({ onFileUpload, onURLAnalyze, isLoading }: UploadZoneProps) {
  const [dragOver, setDragOver] = useState(false);
  const [url, setUrl] = useState('');
  const [activeTab, setActiveTab] = useState<'file' | 'url'>('file');
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);

    const file = e.dataTransfer.files[0];
    if (file) {
      validateAndUpload(file);
    }
  }, [onFileUpload]);

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      validateAndUpload(file);
    }
  }, [onFileUpload]);

  const validateAndUpload = (file: File) => {
    const validTypes = ['.html', '.htm', '.pdf'];
    const ext = file.name.toLowerCase().slice(file.name.lastIndexOf('.'));
    
    if (!validTypes.includes(ext)) {
      alert('Please upload an HTML or PDF file');
      return;
    }

    onFileUpload(file);
  };

  const handleURLSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (url.trim()) {
      // Add protocol if missing
      let finalUrl = url.trim();
      if (!finalUrl.startsWith('http://') && !finalUrl.startsWith('https://')) {
        finalUrl = 'https://' + finalUrl;
      }
      onURLAnalyze(finalUrl);
    }
  };

  return (
    <div className="max-w-2xl mx-auto">
      {/* Tab Switcher */}
      <div className="flex gap-2 mb-6 p-1 bg-zinc-800/50 rounded-lg" role="tablist">
        <button
          role="tab"
          aria-selected={activeTab === 'file'}
          aria-controls="file-panel"
          onClick={() => setActiveTab('file')}
          className={`flex-1 flex items-center justify-center gap-2 py-2.5 px-4 rounded-md font-medium transition-all ${
            activeTab === 'file'
              ? 'bg-zinc-700 text-white'
              : 'text-zinc-400 hover:text-white'
          }`}
        >
          <FileText className="w-4 h-4" aria-hidden="true" />
          Upload File
        </button>
        <button
          role="tab"
          aria-selected={activeTab === 'url'}
          aria-controls="url-panel"
          onClick={() => setActiveTab('url')}
          className={`flex-1 flex items-center justify-center gap-2 py-2.5 px-4 rounded-md font-medium transition-all ${
            activeTab === 'url'
              ? 'bg-zinc-700 text-white'
              : 'text-zinc-400 hover:text-white'
          }`}
        >
          <Globe className="w-4 h-4" aria-hidden="true" />
          Analyze URL
        </button>
      </div>

      {/* File Upload Panel */}
      <div
        id="file-panel"
        role="tabpanel"
        aria-labelledby="file-tab"
        hidden={activeTab !== 'file'}
      >
        <div
          className={`drop-zone ${dragOver ? 'drag-over' : ''} ${isLoading ? 'pointer-events-none opacity-60' : ''}`}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          onKeyDown={(e) => e.key === 'Enter' && fileInputRef.current?.click()}
          tabIndex={0}
          role="button"
          aria-label="Drop files here or click to browse"
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".html,.htm,.pdf"
            onChange={handleFileSelect}
            className="sr-only"
            aria-label="File upload input"
          />

          <div className="flex flex-col items-center text-center">
            {isLoading ? (
              <>
                <div className="relative">
                  <div className="w-16 h-16 rounded-full bg-cyan-500/20 flex items-center justify-center">
                    <Loader2 className="w-8 h-8 text-cyan-400 animate-spin" aria-hidden="true" />
                  </div>
                  <div className="absolute inset-0 rounded-full border-2 border-cyan-500/30 loading-ring" />
                </div>
                <p className="mt-4 text-zinc-300 font-medium">Analyzing document...</p>
                <p className="text-zinc-500 text-sm">This may take a moment</p>
              </>
            ) : (
              <>
                <div className="w-16 h-16 rounded-full bg-zinc-800 flex items-center justify-center mb-4">
                  <Upload className="w-8 h-8 text-cyan-400" aria-hidden="true" />
                </div>
                <p className="text-zinc-300 font-medium mb-2">
                  Drop your file here or click to browse
                </p>
                <p className="text-zinc-500 text-sm">
                  Supports HTML and PDF files up to 50MB
                </p>
              </>
            )}
          </div>
        </div>
      </div>

      {/* URL Analysis Panel */}
      <div
        id="url-panel"
        role="tabpanel"
        aria-labelledby="url-tab"
        hidden={activeTab !== 'url'}
      >
        <form onSubmit={handleURLSubmit} className="space-y-4">
          <div className="relative">
            <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
              <Link className="w-5 h-5 text-zinc-500" aria-hidden="true" />
            </div>
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://example.com"
              className="w-full pl-12 pr-4 py-4 bg-zinc-800 border border-zinc-700 rounded-xl text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-transparent"
              aria-label="Website URL to analyze"
              disabled={isLoading}
            />
          </div>

          <button
            type="submit"
            disabled={!url.trim() || isLoading}
            className="w-full btn btn-primary py-4 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isLoading ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" aria-hidden="true" />
                Analyzing...
              </>
            ) : (
              <>
                <Globe className="w-5 h-5" aria-hidden="true" />
                Analyze Website
              </>
            )}
          </button>

          <p className="text-center text-zinc-500 text-sm">
            We'll render the page and check for accessibility issues
          </p>
        </form>
      </div>
    </div>
  );
}





