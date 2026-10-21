import { useEffect, useState } from "react";
import manifest from "../../public/butler/manifest.json";
import type { Pose } from "./mood";

const [CELL_W, CELL_H] = manifest.cell as [number, number];
type AnimInfo = { frames: number; fps: number; file: string };
const ANIMS = manifest.anims as Record<string, AnimInfo>;

// Idle plays a hand-ordered loop: stand, blink, stand, glance around.
const SEQUENCES: Partial<Record<Pose, number[]>> = {
  idle: [0, 0, 0, 1, 0, 0, 3, 3, 0, 0, 2, 0],
};

export const prefersReducedMotion = () =>
  window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

interface Props {
  pose: Pose;
  scale?: number;
  className?: string;
  label?: string;
}

export function Sprite({ pose, scale = 1, className, label }: Props) {
  const anim = ANIMS[pose] ?? ANIMS.idle;
  const seq = SEQUENCES[pose] ?? Array.from({ length: anim.frames }, (_, i) => i);
  const [step, setStep] = useState(0);

  useEffect(() => {
    setStep(0);
    if (seq.length < 2 || prefersReducedMotion()) return;
    const t = setInterval(() => setStep((s) => (s + 1) % seq.length), 1000 / anim.fps);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pose]);

  const w = CELL_W * scale, h = CELL_H * scale;
  const frame = seq[step % seq.length] ?? 0;
  return (
    <div
      role="img"
      aria-label={label ?? `Butler (${pose})`}
      className={className}
      style={{
        width: w,
        height: h,
        backgroundImage: `url(${import.meta.env.BASE_URL}butler/${anim.file})`,
        backgroundSize: `${w * anim.frames}px ${h}px`,
        backgroundPosition: `${-frame * w}px 0`,
        backgroundRepeat: "no-repeat",
      }}
    />
  );
}

export function Face({ name, size = 48 }: { name: string; size?: number }) {
  const names = manifest.faces.names as string[];
  const i = Math.max(0, names.indexOf(name));
  return (
    <div
      aria-hidden
      style={{
        width: size,
        height: size,
        backgroundImage: `url(${import.meta.env.BASE_URL}butler/faces.png)`,
        backgroundSize: `${size * names.length}px ${size}px`,
        backgroundPosition: `${-i * size}px 0`,
      }}
    />
  );
}
