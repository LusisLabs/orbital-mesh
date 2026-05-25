"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import {
  ArrowUp,
  BrainCog,
  FolderCode,
  Globe,
  Mic,
  Paperclip,
  Square,
  StopCircle,
  X,
} from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import React from "react";

import { cn } from "../../lib/utils";

type TextareaProps = React.TextareaHTMLAttributes<HTMLTextAreaElement>;

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, ...props }, ref) => (
    <textarea
      className={cn(
        "mesh-prompt-textarea flex min-h-[44px] w-full resize-none rounded-md border-none bg-transparent px-3 py-2.5 text-base text-gray-100 placeholder:text-gray-400 focus-visible:outline-none focus-visible:ring-0 disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      ref={ref}
      rows={1}
      {...props}
    />
  ),
);
Textarea.displayName = "Textarea";

const TooltipProvider = TooltipPrimitive.Provider;
const Tooltip = TooltipPrimitive.Root;
const TooltipTrigger = TooltipPrimitive.Trigger;
const TooltipContent = React.forwardRef<
  React.ElementRef<typeof TooltipPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>
>(({ className, sideOffset = 4, ...props }, ref) => (
  <TooltipPrimitive.Content
    ref={ref}
    sideOffset={sideOffset}
    className={cn(
      "z-50 overflow-hidden rounded-md border border-[#333333] bg-[#1f2023] px-3 py-1.5 text-sm text-white shadow-md animate-in fade-in-0 zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95",
      className,
    )}
    {...props}
  />
));
TooltipContent.displayName = TooltipPrimitive.Content.displayName;

const Dialog = DialogPrimitive.Root;
const DialogPortal = DialogPrimitive.Portal;

const DialogOverlay = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    className={cn(
      "fixed inset-0 z-50 bg-black/60 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
      className,
    )}
    {...props}
  />
));
DialogOverlay.displayName = DialogPrimitive.Overlay.displayName;

const DialogContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content>
>(({ className, children, ...props }, ref) => (
  <DialogPortal>
    <DialogOverlay />
    <DialogPrimitive.Content
      ref={ref}
      className={cn(
        "fixed left-[50%] top-[50%] z-50 grid w-full max-w-[90vw] translate-x-[-50%] translate-y-[-50%] gap-4 rounded-2xl border border-[#333333] bg-[#1f2023] p-0 shadow-xl duration-300 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 md:max-w-[800px]",
        className,
      )}
      {...props}
    >
      {children}
      <DialogPrimitive.Close className="absolute right-4 top-4 z-10 rounded-full bg-[#2e3033]/80 p-2 transition-all hover:bg-[#2e3033]">
        <X className="h-5 w-5 text-gray-200 hover:text-white" />
        <span className="sr-only">Close</span>
      </DialogPrimitive.Close>
    </DialogPrimitive.Content>
  </DialogPortal>
));
DialogContent.displayName = DialogPrimitive.Content.displayName;

const DialogTitle = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title
    ref={ref}
    className={cn("text-lg font-semibold leading-none tracking-tight text-gray-100", className)}
    {...props}
  />
));
DialogTitle.displayName = DialogPrimitive.Title.displayName;

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "outline" | "ghost";
  size?: "default" | "sm" | "lg" | "icon";
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "default", type = "button", ...props }, ref) => {
    const variantClasses = {
      default: "bg-white text-black hover:bg-white/80",
      outline: "border border-[#444444] bg-transparent hover:bg-[#3a3a40]",
      ghost: "bg-transparent hover:bg-[#3a3a40]",
    };
    const sizeClasses = {
      default: "h-10 px-4 py-2",
      sm: "h-8 px-3 text-sm",
      lg: "h-12 px-6",
      icon: "h-8 w-8 rounded-full aspect-[1/1]",
    };

    return (
      <button
        className={cn(
          "inline-flex items-center justify-center font-medium transition-colors focus-visible:outline-none disabled:pointer-events-none disabled:opacity-50",
          variantClasses[variant],
          sizeClasses[size],
          className,
        )}
        ref={ref}
        type={type}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";

interface VoiceRecorderProps {
  isRecording: boolean;
  onStartRecording: () => void;
  onStopRecording: (duration: number) => void;
  visualizerBars?: number;
}

const VoiceRecorder: React.FC<VoiceRecorderProps> = ({
  isRecording,
  onStartRecording,
  onStopRecording,
  visualizerBars = 32,
}) => {
  const [time, setTime] = React.useState(0);
  const timerRef = React.useRef<ReturnType<typeof setInterval> | null>(null);
  const wasRecordingRef = React.useRef(false);
  const onStartRef = React.useRef(onStartRecording);
  const onStopRef = React.useRef(onStopRecording);

  React.useEffect(() => {
    onStartRef.current = onStartRecording;
    onStopRef.current = onStopRecording;
  }, [onStartRecording, onStopRecording]);

  React.useEffect(() => {
    if (isRecording) {
      wasRecordingRef.current = true;
      onStartRef.current();
      timerRef.current = setInterval(() => setTime((current) => current + 1), 1000);
      return () => {
        if (timerRef.current) clearInterval(timerRef.current);
        timerRef.current = null;
      };
    }

    if (wasRecordingRef.current) {
      onStopRef.current(time);
      wasRecordingRef.current = false;
      setTime(0);
    }
  }, [isRecording, time]);

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  };

  return (
    <div
      className={cn(
        "flex w-full flex-col items-center justify-center py-3 transition-all duration-300",
        isRecording ? "opacity-100" : "h-0 opacity-0",
      )}
    >
      <div className="mb-3 flex items-center gap-2">
        <div className="h-2 w-2 animate-pulse rounded-full bg-red-500" />
        <span className="font-mono text-sm text-white/80">{formatTime(time)}</span>
      </div>
      <div className="flex h-10 w-full items-center justify-center gap-0.5 px-4">
        {Array.from({ length: visualizerBars }).map((_, index) => (
          <div
            key={index}
            className="w-0.5 animate-pulse rounded-full bg-white/50"
            style={{
              height: `${25 + ((index * 17) % 65)}%`,
              animationDelay: `${index * 0.05}s`,
              animationDuration: `${0.55 + (index % 4) * 0.1}s`,
            }}
          />
        ))}
      </div>
    </div>
  );
};

interface ImageViewDialogProps {
  imageUrl: string | null;
  onClose: () => void;
}

const ImageViewDialog: React.FC<ImageViewDialogProps> = ({ imageUrl, onClose }) => {
  if (!imageUrl) return null;

  return (
    <Dialog open={Boolean(imageUrl)} onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="border-none bg-transparent p-0 shadow-none md:max-w-[800px]">
        <DialogTitle className="sr-only">Image Preview</DialogTitle>
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.95 }}
          transition={{ duration: 0.2, ease: "easeOut" }}
          className="relative overflow-hidden rounded-2xl bg-[#1f2023] shadow-2xl"
        >
          <img
            src={imageUrl}
            alt="Full preview"
            className="max-h-[80vh] w-full rounded-2xl object-contain"
          />
        </motion.div>
      </DialogContent>
    </Dialog>
  );
};

interface PromptInputContextType {
  isLoading: boolean;
  value: string;
  setValue: (value: string) => void;
  maxHeight: number | string;
  onSubmit?: () => void;
  disabled?: boolean;
}

const PromptInputContext = React.createContext<PromptInputContextType>({
  isLoading: false,
  value: "",
  setValue: () => {},
  maxHeight: 240,
  onSubmit: undefined,
  disabled: false,
});

function usePromptInput() {
  const context = React.useContext(PromptInputContext);
  if (!context) throw new Error("usePromptInput must be used within a PromptInput");
  return context;
}

interface PromptInputProps {
  isLoading?: boolean;
  value?: string;
  onValueChange?: (value: string) => void;
  maxHeight?: number | string;
  onSubmit?: () => void;
  children: React.ReactNode;
  className?: string;
  disabled?: boolean;
  onDragOver?: (event: React.DragEvent) => void;
  onDragLeave?: (event: React.DragEvent) => void;
  onDrop?: (event: React.DragEvent) => void;
}

const PromptInput = React.forwardRef<HTMLDivElement, PromptInputProps>(
  (
    {
      className,
      isLoading = false,
      maxHeight = 240,
      value,
      onValueChange,
      onSubmit,
      children,
      disabled = false,
      onDragOver,
      onDragLeave,
      onDrop,
    },
    ref,
  ) => {
    const [internalValue, setInternalValue] = React.useState(value || "");
    const handleChange = (newValue: string) => {
      setInternalValue(newValue);
      onValueChange?.(newValue);
    };

    return (
      <TooltipProvider>
        <PromptInputContext.Provider
          value={{
            isLoading,
            value: value ?? internalValue,
            setValue: onValueChange ?? handleChange,
            maxHeight,
            onSubmit,
            disabled,
          }}
        >
          <div
            ref={ref}
            className={cn(
              "rounded-3xl border border-[#444444] bg-[#1f2023] p-2 shadow-[0_8px_30px_rgba(0,0,0,0.24)] transition-all duration-300",
              isLoading && "border-red-500/70",
              className,
            )}
            onDragOver={onDragOver}
            onDragLeave={onDragLeave}
            onDrop={onDrop}
          >
            {children}
          </div>
        </PromptInputContext.Provider>
      </TooltipProvider>
    );
  },
);
PromptInput.displayName = "PromptInput";

interface PromptInputTextareaProps {
  disableAutosize?: boolean;
  placeholder?: string;
}

const PromptInputTextarea: React.FC<PromptInputTextareaProps & React.ComponentProps<typeof Textarea>> = ({
  className,
  onKeyDown,
  disableAutosize = false,
  placeholder,
  ...props
}) => {
  const { value, setValue, maxHeight, onSubmit, disabled } = usePromptInput();
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);

  React.useEffect(() => {
    if (disableAutosize || !textareaRef.current) return;
    textareaRef.current.style.height = "auto";
    textareaRef.current.style.height =
      typeof maxHeight === "number"
        ? `${Math.min(textareaRef.current.scrollHeight, maxHeight)}px`
        : `min(${textareaRef.current.scrollHeight}px, ${maxHeight})`;
  }, [value, maxHeight, disableAutosize]);

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      onSubmit?.();
    }
    onKeyDown?.(event);
  };

  return (
    <Textarea
      ref={textareaRef}
      value={value}
      onChange={(event) => setValue(event.target.value)}
      onKeyDown={handleKeyDown}
      className={cn("text-base", className)}
      disabled={disabled}
      placeholder={placeholder}
      {...props}
    />
  );
};

type PromptInputActionsProps = React.HTMLAttributes<HTMLDivElement>;

const PromptInputActions: React.FC<PromptInputActionsProps> = ({ children, className, ...props }) => (
  <div className={cn("flex items-center gap-2", className)} {...props}>
    {children}
  </div>
);

interface PromptInputActionProps extends React.ComponentProps<typeof Tooltip> {
  tooltip: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  side?: "top" | "bottom" | "left" | "right";
}

const PromptInputAction: React.FC<PromptInputActionProps> = ({
  tooltip,
  children,
  className,
  side = "top",
  ...props
}) => (
  <Tooltip {...props}>
    <TooltipTrigger asChild>{children}</TooltipTrigger>
    <TooltipContent side={side} className={className}>
      {tooltip}
    </TooltipContent>
  </Tooltip>
);

const CustomDivider: React.FC = () => (
  <div className="relative mx-1 h-6 w-[1.5px]">
    <div
      className="absolute inset-0 rounded-full bg-gradient-to-t from-transparent via-[#9b87f5]/70 to-transparent"
      style={{
        clipPath: "polygon(0% 0%, 100% 0%, 100% 40%, 140% 50%, 100% 60%, 100% 100%, 0% 100%, 0% 60%, -40% 50%, 0% 40%)",
      }}
    />
  </div>
);

export interface PromptInputBoxProps {
  onSend?: (message: string, files?: File[]) => void;
  isLoading?: boolean;
  placeholder?: string;
  className?: string;
}

export const PromptInputBox = React.forwardRef<HTMLDivElement, PromptInputBoxProps>(
  ({ onSend = () => {}, isLoading = false, placeholder = "Ask Harper-696 about Mesh state...", className }, ref) => {
    const [input, setInput] = React.useState("");
    const [files, setFiles] = React.useState<File[]>([]);
    const [filePreviews, setFilePreviews] = React.useState<Record<string, string>>({});
    const [selectedImage, setSelectedImage] = React.useState<string | null>(null);
    const [isRecording, setIsRecording] = React.useState(false);
    const [showSearch, setShowSearch] = React.useState(false);
    const [showThink, setShowThink] = React.useState(false);
    const [showCanvas, setShowCanvas] = React.useState(false);
    const uploadInputRef = React.useRef<HTMLInputElement>(null);

    const handleToggleChange = (value: string) => {
      if (value === "search") {
        setShowSearch((previous) => !previous);
        setShowThink(false);
      } else if (value === "think") {
        setShowThink((previous) => !previous);
        setShowSearch(false);
      }
    };

    const isImageFile = (file: File) => file.type.startsWith("image/");

    const processFile = React.useCallback((file: File) => {
      if (!isImageFile(file) || file.size > 10 * 1024 * 1024) return;
      setFiles([file]);
      const reader = new FileReader();
      reader.onload = (event) => setFilePreviews({ [file.name]: event.target?.result as string });
      reader.readAsDataURL(file);
    }, []);

    const handleDragOver = React.useCallback((event: React.DragEvent) => {
      event.preventDefault();
      event.stopPropagation();
    }, []);

    const handleDrop = React.useCallback((event: React.DragEvent) => {
      event.preventDefault();
      event.stopPropagation();
      const imageFiles = Array.from(event.dataTransfer.files).filter((file) => isImageFile(file));
      if (imageFiles.length > 0 && imageFiles[0]) processFile(imageFiles[0]);
    }, [processFile]);

    const handleRemoveFile = (index: number) => {
      const fileToRemove = files[index];
      if (fileToRemove && filePreviews[fileToRemove.name]) setFilePreviews({});
      setFiles([]);
    };

    const handlePaste = React.useCallback((event: ClipboardEvent) => {
      const items = event.clipboardData?.items;
      if (!items) return;
      for (let index = 0; index < items.length; index += 1) {
        if (items[index]?.type.includes("image")) {
          const file = items[index]?.getAsFile();
          if (file) {
            event.preventDefault();
            processFile(file);
            break;
          }
        }
      }
    }, [processFile]);

    React.useEffect(() => {
      document.addEventListener("paste", handlePaste);
      return () => document.removeEventListener("paste", handlePaste);
    }, [handlePaste]);

    const handleSubmit = () => {
      if (!input.trim() && files.length === 0) return;

      let messagePrefix = "";
      if (showSearch) messagePrefix = "[Search: ";
      else if (showThink) messagePrefix = "[Think: ";
      else if (showCanvas) messagePrefix = "[Canvas: ";

      const formattedInput = messagePrefix ? `${messagePrefix}${input}]` : input;
      onSend(formattedInput, files);
      setInput("");
      setFiles([]);
      setFilePreviews({});
    };

    const handleStopRecording = (duration: number) => {
      setIsRecording(false);
      onSend(`[Voice message - ${duration} seconds]`, []);
    };

    const hasContent = input.trim() !== "" || files.length > 0;

    return (
      <>
        <PromptInput
          value={input}
          onValueChange={setInput}
          isLoading={isLoading}
          onSubmit={handleSubmit}
          className={cn(
            "w-full border-[#444444] bg-[#1f2023] shadow-[0_8px_30px_rgba(0,0,0,0.24)] transition-all duration-300 ease-in-out",
            isRecording && "border-red-500/70",
            className,
          )}
          disabled={isLoading || isRecording}
          ref={ref}
          onDragOver={handleDragOver}
          onDragLeave={handleDragOver}
          onDrop={handleDrop}
        >
          {files.length > 0 && !isRecording ? (
            <div className="flex flex-wrap gap-2 p-0 pb-1 transition-all duration-300">
              {files.map((file, index) => (
                <div key={file.name} className="group relative">
                  {file.type.startsWith("image/") && filePreviews[file.name] ? (
                    <button
                      type="button"
                      className="h-16 w-16 cursor-pointer overflow-hidden rounded-xl transition-all"
                      onClick={() => setSelectedImage(filePreviews[file.name] ?? null)}
                    >
                      <img src={filePreviews[file.name]} alt={file.name} className="h-full w-full object-cover" />
                    </button>
                  ) : null}
                  <button
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      handleRemoveFile(index);
                    }}
                    aria-label={`Remove ${file.name}`}
                    className="absolute right-1 top-1 rounded-full bg-black/70 p-0.5"
                  >
                    <X className="h-3 w-3 text-white" />
                  </button>
                </div>
              ))}
            </div>
          ) : null}

          <div className={cn("transition-all duration-300", isRecording ? "h-0 overflow-hidden opacity-0" : "opacity-100")}>
            <PromptInputTextarea
              placeholder={
                showSearch
                  ? "Search Mesh docs or web context..."
                  : showThink
                    ? "Ask Harper to reason through blockers..."
                    : showCanvas
                      ? "Create an agent canvas..."
                      : placeholder
              }
              className="text-base"
            />
          </div>

          {isRecording ? (
            <VoiceRecorder
              isRecording={isRecording}
              onStartRecording={() => undefined}
              onStopRecording={handleStopRecording}
            />
          ) : null}

          <PromptInputActions className="flex items-center justify-between gap-2 p-0 pt-2">
            <div className={cn("flex items-center gap-1 transition-opacity duration-300", isRecording ? "invisible h-0 opacity-0" : "visible opacity-100")}>
              <PromptInputAction tooltip="Upload image">
                <button
                  type="button"
                  onClick={() => uploadInputRef.current?.click()}
                  className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-full text-[#9ca3af] transition-colors hover:bg-gray-600/30 hover:text-[#d1d5db]"
                  disabled={isRecording}
                >
                  <Paperclip className="h-5 w-5 transition-colors" />
                  <input
                    ref={uploadInputRef}
                    type="file"
                    className="hidden"
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (file) processFile(file);
                      event.currentTarget.value = "";
                    }}
                    accept="image/*"
                  />
                </button>
              </PromptInputAction>

              <div className="flex items-center">
                <button
                  type="button"
                  onClick={() => handleToggleChange("search")}
                  className={cn(
                    "flex h-8 items-center gap-1 rounded-full border px-2 py-1 transition-all",
                    showSearch
                      ? "border-[#1eaedb] bg-[#1eaedb]/15 text-[#1eaedb]"
                      : "border-transparent bg-transparent text-[#9ca3af] hover:text-[#d1d5db]",
                  )}
                >
                  <motion.span
                    className="flex h-5 w-5 flex-shrink-0 items-center justify-center"
                    animate={{ rotate: showSearch ? 360 : 0, scale: showSearch ? 1.1 : 1 }}
                    whileHover={{ rotate: showSearch ? 360 : 15, scale: 1.1 }}
                    transition={{ type: "spring", stiffness: 260, damping: 25 }}
                  >
                    <Globe className="h-4 w-4" />
                  </motion.span>
                  <AnimatePresence>
                    {showSearch ? (
                      <motion.span
                        initial={{ width: 0, opacity: 0 }}
                        animate={{ width: "auto", opacity: 1 }}
                        exit={{ width: 0, opacity: 0 }}
                        transition={{ duration: 0.2 }}
                        className="flex-shrink-0 overflow-hidden whitespace-nowrap text-xs text-[#1eaedb]"
                      >
                        Search
                      </motion.span>
                    ) : null}
                  </AnimatePresence>
                </button>

                <CustomDivider />

                <button
                  type="button"
                  onClick={() => handleToggleChange("think")}
                  className={cn(
                    "flex h-8 items-center gap-1 rounded-full border px-2 py-1 transition-all",
                    showThink
                      ? "border-[#8b5cf6] bg-[#8b5cf6]/15 text-[#8b5cf6]"
                      : "border-transparent bg-transparent text-[#9ca3af] hover:text-[#d1d5db]",
                  )}
                >
                  <motion.span
                    className="flex h-5 w-5 flex-shrink-0 items-center justify-center"
                    animate={{ rotate: showThink ? 360 : 0, scale: showThink ? 1.1 : 1 }}
                    whileHover={{ rotate: showThink ? 360 : 15, scale: 1.1 }}
                    transition={{ type: "spring", stiffness: 260, damping: 25 }}
                  >
                    <BrainCog className="h-4 w-4" />
                  </motion.span>
                  <AnimatePresence>
                    {showThink ? (
                      <motion.span
                        initial={{ width: 0, opacity: 0 }}
                        animate={{ width: "auto", opacity: 1 }}
                        exit={{ width: 0, opacity: 0 }}
                        transition={{ duration: 0.2 }}
                        className="flex-shrink-0 overflow-hidden whitespace-nowrap text-xs text-[#8b5cf6]"
                      >
                        Think
                      </motion.span>
                    ) : null}
                  </AnimatePresence>
                </button>

                <CustomDivider />

                <button
                  type="button"
                  onClick={() => setShowCanvas((previous) => !previous)}
                  className={cn(
                    "flex h-8 items-center gap-1 rounded-full border px-2 py-1 transition-all",
                    showCanvas
                      ? "border-[#f97316] bg-[#f97316]/15 text-[#f97316]"
                      : "border-transparent bg-transparent text-[#9ca3af] hover:text-[#d1d5db]",
                  )}
                >
                  <motion.span
                    className="flex h-5 w-5 flex-shrink-0 items-center justify-center"
                    animate={{ rotate: showCanvas ? 360 : 0, scale: showCanvas ? 1.1 : 1 }}
                    whileHover={{ rotate: showCanvas ? 360 : 15, scale: 1.1 }}
                    transition={{ type: "spring", stiffness: 260, damping: 25 }}
                  >
                    <FolderCode className="h-4 w-4" />
                  </motion.span>
                  <AnimatePresence>
                    {showCanvas ? (
                      <motion.span
                        initial={{ width: 0, opacity: 0 }}
                        animate={{ width: "auto", opacity: 1 }}
                        exit={{ width: 0, opacity: 0 }}
                        transition={{ duration: 0.2 }}
                        className="flex-shrink-0 overflow-hidden whitespace-nowrap text-xs text-[#f97316]"
                      >
                        Canvas
                      </motion.span>
                    ) : null}
                  </AnimatePresence>
                </button>
              </div>
            </div>

            <PromptInputAction tooltip={isLoading ? "Stop generation" : isRecording ? "Stop recording" : hasContent ? "Send message" : "Voice message"}>
              <Button
                variant="default"
                size="icon"
                className={cn(
                  "h-8 w-8 rounded-full transition-all duration-200",
                  isRecording
                    ? "bg-transparent text-red-500 hover:bg-gray-600/30 hover:text-red-400"
                    : hasContent
                      ? "bg-white text-[#1f2023] hover:bg-white/80"
                      : "bg-transparent text-[#9ca3af] hover:bg-gray-600/30 hover:text-[#d1d5db]",
                )}
                onClick={() => {
                  if (isRecording) setIsRecording(false);
                  else if (hasContent) handleSubmit();
                  else setIsRecording(true);
                }}
                disabled={isLoading && !hasContent}
              >
                {isLoading ? (
                  <Square className="h-4 w-4 animate-pulse fill-[#1f2023]" />
                ) : isRecording ? (
                  <StopCircle className="h-5 w-5 text-red-500" />
                ) : hasContent ? (
                  <ArrowUp className="h-4 w-4 text-[#1f2023]" />
                ) : (
                  <Mic className="h-5 w-5" />
                )}
              </Button>
            </PromptInputAction>
          </PromptInputActions>
        </PromptInput>

        <ImageViewDialog imageUrl={selectedImage} onClose={() => setSelectedImage(null)} />
      </>
    );
  },
);
PromptInputBox.displayName = "PromptInputBox";
