export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "date unknown";
  const d = new Date(iso);
  const days = Math.floor((Date.now() - d.getTime()) / 86_400_000);
  if (days < 1) return "today";
  if (days < 2) return "yesterday";
  if (days < 7) return `${days} days ago`;
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

export function clock(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  const sameDay = d.toDateString() === new Date().toDateString();
  const t = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  return sameDay ? t : `${d.toLocaleDateString([], { weekday: "short" })} ${t}`;
}

export function authors(list: string[]): string {
  if (list.length <= 3) return list.join(", ");
  return `${list.slice(0, 3).join(", ")} and ${list.length - 3} more`;
}
