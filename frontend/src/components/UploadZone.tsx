import { useState, useCallback, useRef } from 'react';
import { Upload, FileText, Loader2 } from 'lucide-react';

interface UploadZoneProps {
  onFileUpload: (file: File) => void;
  isLoading: boolean;
}

export function UploadZone({ onFileUpload, isLoading }: UploadZoneProps) {
  const [dragOver, setDragOver] = useState(false);
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
    if (file) validateAndUpload(file);
  }, [onFileUpload]);

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) validateAndUpload(file);
  }, [onFileUpload]);

  const validateAndUpload = (file: File) => {
    const ext = file.name.toLowerCase().slice(file.name.lastIndexOf('.'));
    if (ext !== '.pdf') {
      alert('Please upload a PDF file.');
      return;
    }
    onFileUpload(file);
  };

  return (
    <div className="max-w-2xl mx-auto">
      <div
        className={`drop-zone ${dragOver ? 'drag-over' : ''} ${isLoading ? 'pointer-events-none' : ''}`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => !isLoading && fileInputRef.current?.click()}
        onKeyDown={(e) => e.key === 'Enter' && !isLoading && fileInputRef.current?.click()}
        tabIndex={0}
        role="button"
        aria-label="Drop a PDF file here or press Enter to browse"
        style={{ opacity: isLoading ? 0.55 : 1 }}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf"
          onChange={handleFileSelect}
          className="sr-only"
          aria-label="PDF file upload"
        />

        <div className="flex flex-col items-center text-center gap-5">
          {isLoading ? (
            <>
              {/* Loading state */}
              <div className="relative">
                <div
                  className="w-16 h-16 rounded-full flex items-center justify-center"
                  style={{ background: 'rgba(37, 99, 235, 0.10)' }}
                >
                  <Loader2
                    className="w-7 h-7 animate-spin"
                    style={{ color: '#60a5fa' }}
                    aria-hidden="true"
                  />
                </div>
                <div
                  className="absolute inset-0 rounded-full loading-ring"
                  style={{ border: '1.5px solid rgba(37, 99, 235, 0.25)' }}
                />
              </div>
              <div>
                <p className="font-semibold text-sm" style={{ color: '#c8d8e8' }}>
                  Analysing document…
                </p>
                <p className="text-sm mt-1" style={{ color: '#4a607a' }}>
                  Larger PDFs may take a moment
                </p>
              </div>
            </>
          ) : (
            <>
              {/* Idle state */}
              <div
                className="w-16 h-16 rounded-full flex items-center justify-center"
                style={{ background: '#111c2d' }}
              >
                <Upload className="w-7 h-7" style={{ color: '#60a5fa' }} aria-hidden="true" />
              </div>

              <div>
                <p className="font-semibold text-sm mb-1.5" style={{ color: '#c8d8e8' }}>
                  Drop your PDF here
                </p>
                <p className="text-sm" style={{ color: '#4a607a' }}>
                  or click to browse — up to 50 MB
                </p>
              </div>

              {/* Accepted format pill */}
              <div
                className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium"
                style={{
                  background: 'rgba(17, 28, 45, 0.8)',
                  border: '1px solid #1a2840',
                  color: '#4a607a',
                }}
              >
                <FileText className="w-3.5 h-3.5" aria-hidden="true" />
                PDF files only
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
