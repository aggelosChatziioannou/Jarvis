import { useRef, useEffect } from 'react';
import gsap from 'gsap';
import type { VoiceState } from '@/hooks/useVoiceState';

interface OrbCoreProps {
  state: VoiceState;
}

interface AnimParams {
  orbScale: number;
  glowIntensity: number;
  particleSpeed: number;
  coreOpacity: number;
  ringOpacity: number;
}

const PARAM_MAP: Record<VoiceState, Partial<AnimParams>> = {
  idle: { orbScale: 1, glowIntensity: 0.3, particleSpeed: 0.3, coreOpacity: 0.4, ringOpacity: 0.15 },
  listening: { orbScale: 1.08, glowIntensity: 0.6, particleSpeed: 0.8, coreOpacity: 0.7, ringOpacity: 0.35 },
  thinking: { orbScale: 1.15, glowIntensity: 0.9, particleSpeed: 2.5, coreOpacity: 0.85, ringOpacity: 0.6 },
  speaking: { orbScale: 1.25, glowIntensity: 1.0, particleSpeed: 1.2, coreOpacity: 1.0, ringOpacity: 0.8 },
};

interface Particle {
  angle: number;
  radius: number;
  speed: number;
  size: number;
  opacity: number;
  trail: { x: number; y: number }[];
}

export default function OrbCore({ state }: OrbCoreProps) {
  const orbRef = useRef<HTMLDivElement>(null);
  const glowRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animParamsRef = useRef<AnimParams>({
    orbScale: 1,
    glowIntensity: 0.3,
    particleSpeed: 0.3,
    coreOpacity: 0.4,
    ringOpacity: 0.15,
  });
  const stateRef = useRef<VoiceState>('idle');
  const rafRef = useRef(0);
  const pulseTweensRef = useRef<gsap.core.Tween[]>([]);
  const frameRef = useRef(0);

  stateRef.current = state;

  // GSAP state transitions
  useEffect(() => {
    const params = animParamsRef.current;
    const target = PARAM_MAP[state];

    pulseTweensRef.current.forEach(t => t.kill());
    pulseTweensRef.current = [];

    gsap.to(params, {
      orbScale: target.orbScale,
      glowIntensity: target.glowIntensity,
      particleSpeed: target.particleSpeed,
      coreOpacity: target.coreOpacity,
      ringOpacity: target.ringOpacity,
      duration: 0.6,
      ease: 'power2.inOut',
    });

    // Speaking: dynamic pulse
    if (state === 'speaking') {
      const pulse = gsap.to(params, {
        orbScale: 1.35,
        glowIntensity: 1.2,
        duration: 0.6,
        yoyo: true,
        repeat: -1,
        ease: 'sine.inOut',
      });
      pulseTweensRef.current.push(pulse);
    }

    // Idle: gentle breathing
    if (state === 'idle') {
      const breath = gsap.to(params, {
        orbScale: 1.04,
        glowIntensity: 0.4,
        duration: 2.5,
        yoyo: true,
        repeat: -1,
        ease: 'sine.inOut',
      });
      pulseTweensRef.current.push(breath);
    }

    // Thinking: nervous jitter
    if (state === 'thinking') {
      const jitter = gsap.to(params, {
        orbScale: 1.1,
        glowIntensity: 0.7,
        duration: 0.15,
        yoyo: true,
        repeat: -1,
        ease: 'steps(2)',
      });
      pulseTweensRef.current.push(jitter);
    }

    // Update CSS transforms
    if (orbRef.current) {
      gsap.to(orbRef.current, {
        scale: target.orbScale ?? 1,
        duration: 0.6,
        ease: 'power2.inOut',
      });
    }
  }, [state]);

  // Particle animation (Canvas 2D)
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = Math.min(window.devicePixelRatio, 2);
    const size = 320;
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    ctx.scale(dpr, dpr);

    // Create particles - 3 rings of orbiting dots
    const particles: Particle[] = [];

    // Inner ring
    for (let i = 0; i < 12; i++) {
      particles.push({
        angle: (i / 12) * Math.PI * 2,
        radius: 55 + Math.random() * 10,
        speed: 0.008 + Math.random() * 0.004,
        size: 1.5 + Math.random(),
        opacity: 0.3 + Math.random() * 0.3,
        trail: [],
      });
    }

    // Middle ring
    for (let i = 0; i < 18; i++) {
      particles.push({
        angle: (i / 18) * Math.PI * 2,
        radius: 85 + Math.random() * 15,
        speed: 0.005 + Math.random() * 0.003,
        size: 1 + Math.random() * 0.8,
        opacity: 0.2 + Math.random() * 0.25,
        trail: [],
      });
    }

    // Outer ring
    for (let i = 0; i < 24; i++) {
      particles.push({
        angle: (i / 24) * Math.PI * 2,
        radius: 120 + Math.random() * 20,
        speed: 0.003 + Math.random() * 0.002,
        size: 0.8 + Math.random() * 0.6,
        opacity: 0.15 + Math.random() * 0.2,
        trail: [],
      });
    }

    const animate = () => {
      rafRef.current = requestAnimationFrame(animate);
      frameRef.current += 1;

      const params = animParamsRef.current;
      const currentState = stateRef.current;
      const cx = size / 2;
      const cy = size / 2;

      ctx.clearRect(0, 0, size, size);

      // Draw orbital rings (subtle)
      const ringColor = currentState === 'listening'
        ? '0, 229, 160'
        : '255, 184, 0';

      [55, 85, 120].forEach((r, i) => {
        ctx.beginPath();
        ctx.arc(cx, cy, r, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(${ringColor}, ${params.ringOpacity * (0.5 - i * 0.12)})`;
        ctx.lineWidth = 0.5;
        ctx.stroke();
      });

      // Draw particles
      particles.forEach(p => {
        p.angle += p.speed * params.particleSpeed * (currentState === 'thinking' ? 3 : 1);

        const x = cx + Math.cos(p.angle) * p.radius;
        const y = cy + Math.sin(p.angle) * p.radius;

        // Update trail
        p.trail.push({ x, y });
        if (p.trail.length > 8) p.trail.shift();

        // Draw trail
        if (p.trail.length > 2 && params.particleSpeed > 0.5) {
          ctx.beginPath();
          ctx.moveTo(p.trail[0].x, p.trail[0].y);
          for (let i = 1; i < p.trail.length; i++) {
            ctx.lineTo(p.trail[i].x, p.trail[i].y);
          }
          ctx.strokeStyle = `rgba(${ringColor}, ${p.opacity * params.particleSpeed * 0.15})`;
          ctx.lineWidth = 0.5;
          ctx.stroke();
        }

        // Draw dot
        ctx.beginPath();
        ctx.arc(x, y, p.size, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${ringColor}, ${p.opacity * params.coreOpacity})`;
        ctx.fill();

        // Glow for larger particles
        if (p.size > 1.2) {
          ctx.beginPath();
          ctx.arc(x, y, p.size * 3, 0, Math.PI * 2);
          const gradient = ctx.createRadialGradient(x, y, 0, x, y, p.size * 3);
          gradient.addColorStop(0, `rgba(${ringColor}, ${p.opacity * params.coreOpacity * 0.3})`);
          gradient.addColorStop(1, `rgba(${ringColor}, 0)`);
          ctx.fillStyle = gradient;
          ctx.fill();
        }
      });
    };

    animate();

    return () => {
      cancelAnimationFrame(rafRef.current);
    };
  }, []);

  return (
    <div style={{ position: 'relative', width: 320, height: 320 }}>
      {/* Particle canvas */}
      <canvas
        ref={canvasRef}
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          width: 320,
          height: 320,
          pointerEvents: 'none',
        }}
      />

      {/* Core orb */}
      <div
        style={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          width: 80,
          height: 80,
        }}
      >
        {/* Outer glow */}
        <div
          ref={glowRef}
          style={{
            position: 'absolute',
            inset: -30,
            borderRadius: '50%',
            background: 'radial-gradient(circle, rgba(255,184,0,0.25) 0%, rgba(255,140,0,0.08) 40%, transparent 70%)',
            animation: 'orbPulse 3s ease-in-out infinite',
            pointerEvents: 'none',
          }}
        />

        {/* Main orb */}
        <div
          ref={orbRef}
          style={{
            width: '100%',
            height: '100%',
            borderRadius: '50%',
            background: 'radial-gradient(circle at 35% 30%, #FFE055 0%, #FFB800 30%, #FF8C00 60%, #CC5500 100%)',
            boxShadow: `
              0 0 30px rgba(255,184,0,0.5),
              0 0 60px rgba(255,140,0,0.3),
              0 0 100px rgba(255,100,0,0.15),
              inset 0 -4px 12px rgba(0,0,0,0.3)
            `,
            position: 'relative',
          }}
        >
          {/* Inner highlight */}
          <div
            style={{
              position: 'absolute',
              top: '18%',
              left: '22%',
              width: '35%',
              height: '25%',
              borderRadius: '50%',
              background: 'radial-gradient(ellipse, rgba(255,255,255,0.5) 0%, transparent 70%)',
              filter: 'blur(2px)',
            }}
          />
        </div>
      </div>
    </div>
  );
}
