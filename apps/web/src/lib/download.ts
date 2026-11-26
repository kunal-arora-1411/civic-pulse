/** Hand a fetched file to the browser as a download. */
export function saveFile(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.rel = "noopener";
  link.hidden = true;
  document.body.append(link);
  link.click();
  link.remove();
  // Revoking at once cancels the download in Safari; a task is enough.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
