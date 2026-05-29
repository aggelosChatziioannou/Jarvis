import { useRef, useEffect } from 'react';
import * as THREE from 'three';
import gsap from 'gsap';
import type { VoiceState } from '@/hooks/useVoiceState';

interface WaveformRingsProps {
  state: VoiceState;
}

interface AnimParams {
  amplitude: number;
  frequency: number;
  rotationSpeed: number;
  opacity: number;
  r: number;
  g: number;
  b: number;
}

const COLOR_MAP: Record<VoiceState, { r: number; g: number; b: number }> = {
  idle: { r: 0, g: 0.33, b: 0.4 },
  listening: { r: 0, g: 0.53, b: 0.67 },
  thinking: { r: 0, g: 0.67, b: 0.8 },
  synthesizing: { r: 0.4, g: 0.45, b: 0.7 },
  speaking: { r: 0, g: 0.83, b: 1 },
};

const PARAM_MAP: Record<VoiceState, Partial<AnimParams>> = {
  idle: { amplitude: 0.02, frequency: 3.0, rotationSpeed: 0.001, opacity: 0.25 },
  listening: { amplitude: 0.05, frequency: 5.0, rotationSpeed: 0.002, opacity: 0.5 },
  thinking: { amplitude: 0.15, frequency: 12.0, rotationSpeed: 0.008, opacity: 0.7 },
  synthesizing: { amplitude: 0.04, frequency: 3.5, rotationSpeed: 0.0015, opacity: 0.35 },
  speaking: { amplitude: 0.3, frequency: 8.0, rotationSpeed: 0.003, opacity: 0.95 },
};

export default function WaveformRings({ state }: WaveformRingsProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.OrthographicCamera | null>(null);
  const ringsRef = useRef<THREE.LineLoop[]>([]);
  const animParamsRef = useRef<AnimParams>({
    amplitude: 0.02,
    frequency: 3.0,
    rotationSpeed: 0.001,
    opacity: 0.25,
    r: 0,
    g: 0.33,
    b: 0.4,
  });
  const stateRef = useRef<VoiceState>('idle');
  const frameRef = useRef(0);
  const rafRef = useRef(0);
  const pulseTweensRef = useRef<gsap.core.Tween[]>([]);
  const baseAmplitudeRef = useRef(0.02);

  stateRef.current = state;

  // Initialize Three.js
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const width = 180;
    const height = 180;

    // Renderer
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.domElement.style.width = '180px';
    renderer.domElement.style.height = '180px';
    renderer.domElement.style.borderRadius = '50%';
    container.appendChild(renderer.domElement);
    rendererRef.current = renderer;

    // Scene & Camera
    const scene = new THREE.Scene();
    sceneRef.current = scene;

    const aspect = 1;
    const frustum = 1.8;
    const camera = new THREE.OrthographicCamera(
      -frustum * aspect, frustum * aspect,
      frustum, -frustum,
      0.1, 100
    );
    camera.position.set(2, 2, 2);
    camera.lookAt(0, 0, 0);
    cameraRef.current = camera;

    // Create 4 concentric rings
    const ringConfigs = [
      { radius: 1.0, yOffset: -0.3 },
      { radius: 0.75, yOffset: -0.1 },
      { radius: 0.55, yOffset: 0.1 },
      { radius: 0.35, yOffset: 0.3 },
    ];

    const segments = 128;
    const rings: THREE.LineLoop[] = [];

    ringConfigs.forEach(({ radius, yOffset }) => {
      const geometry = new THREE.BufferGeometry();
      const positions = new Float32Array((segments + 1) * 3);

      for (let i = 0; i <= segments; i++) {
        const angle = (i / segments) * Math.PI * 2;
        positions[i * 3] = Math.cos(angle) * radius;
        positions[i * 3 + 1] = yOffset;
        positions[i * 3 + 2] = Math.sin(angle) * radius;
      }

      geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));

      const material = new THREE.LineBasicMaterial({
        color: new THREE.Color(0, 0.33, 0.4),
        transparent: true,
        opacity: 0.25,
      });

      const ring = new THREE.LineLoop(geometry, material);
      scene.add(ring);
      rings.push(ring);
    });

    ringsRef.current = rings;

    // Animation loop
    const animate = () => {
      rafRef.current = requestAnimationFrame(animate);
      const params = animParamsRef.current;
      const currentState = stateRef.current;
      frameRef.current += 1;
      const time = frameRef.current * 0.016;

      // Rotate entire ring group
      rings.forEach((ring, i) => {
        ring.rotation.y += params.rotationSpeed * (i % 2 === 0 ? 1 : -1);

        // Update vertex positions
        const positions = ring.geometry.attributes.position.array as Float32Array;
        const ringConfig = ringConfigs[i];
        const radius = ringConfig.radius;
        const yOffset = ringConfig.yOffset;

        for (let j = 0; j <= segments; j++) {
          const angle = (j / segments) * Math.PI * 2;
          const vertexAngle = angle + time * params.frequency * 0.5;

          let amp = params.amplitude;

          // Speaking state: dynamic variation per ring
          if (currentState === 'speaking') {
            const ringPhase = i * 0.7 + time * 2;
            amp *= (0.6 + 0.4 * Math.sin(ringPhase));
          }

          const displacement = Math.sin(vertexAngle * params.frequency + i) * amp;

          positions[j * 3] = Math.cos(angle) * radius;
          positions[j * 3 + 1] = yOffset + displacement;
          positions[j * 3 + 2] = Math.sin(angle) * radius;
        }

        ring.geometry.attributes.position.needsUpdate = true;

        // Update color
        const color = new THREE.Color(params.r, params.g, params.b);
        (ring.material as THREE.LineBasicMaterial).color.copy(color);
        (ring.material as THREE.LineBasicMaterial).opacity = params.opacity;
      });

      renderer.render(scene, camera);
    };

    animate();

    // Idle ambient animation
    const idleAmpTween = gsap.to(animParamsRef.current, {
      amplitude: 0.025,
      duration: 3,
      yoyo: true,
      repeat: -1,
      ease: 'sine.inOut',
    });

    const idleOpacityTween = gsap.to(animParamsRef.current, {
      opacity: 0.3,
      duration: 4,
      yoyo: true,
      repeat: -1,
      ease: 'sine.inOut',
    });

    pulseTweensRef.current.push(idleAmpTween, idleOpacityTween);

    return () => {
      cancelAnimationFrame(rafRef.current);
      pulseTweensRef.current.forEach(t => t.kill());
      pulseTweensRef.current = [];
      rings.forEach(ring => {
        ring.geometry.dispose();
        (ring.material as THREE.LineBasicMaterial).dispose();
      });
      renderer.dispose();
      if (container.contains(renderer.domElement)) {
        container.removeChild(renderer.domElement);
      }
    };
  }, []);

  // State change: animate parameters
  useEffect(() => {
    const params = animParamsRef.current;
    const target = PARAM_MAP[state];
    const targetColor = COLOR_MAP[state];

    // Kill previous ambient tweens
    pulseTweensRef.current.forEach(t => t.kill());
    pulseTweensRef.current = [];

    baseAmplitudeRef.current = target.amplitude ?? 0.02;

    // Main transition tween
    gsap.to(params, {
      amplitude: target.amplitude,
      frequency: target.frequency,
      rotationSpeed: target.rotationSpeed,
      opacity: target.opacity,
      r: targetColor.r,
      g: targetColor.g,
      b: targetColor.b,
      duration: 0.6,
      ease: 'power2.inOut',
    });

    // Speaking: add dynamic pulse overlay
    if (state === 'speaking') {
      const speakPulse = gsap.to(params, {
        amplitude: 0.4,
        opacity: 1.0,
        duration: 0.8,
        yoyo: true,
        repeat: -1,
        ease: 'sine.inOut',
      });
      pulseTweensRef.current.push(speakPulse);
    }

    // Synthesizing: gentle ambient pulse
    if (state === 'synthesizing') {
      const synthPulse = gsap.to(params, {
        amplitude: 0.06,
        opacity: 0.45,
        duration: 2.5,
        yoyo: true,
        repeat: -1,
        ease: 'sine.inOut',
      });
      pulseTweensRef.current.push(synthPulse);
    }

    // Idle: restore ambient heartbeat
    if (state === 'idle') {
      const idleAmp = gsap.to(params, {
        amplitude: 0.025,
        duration: 3,
        yoyo: true,
        repeat: -1,
        ease: 'sine.inOut',
      });
      const idleOp = gsap.to(params, {
        opacity: 0.3,
        duration: 4,
        yoyo: true,
        repeat: -1,
        ease: 'sine.inOut',
      });
      pulseTweensRef.current.push(idleAmp, idleOp);
    }
  }, [state]);

  return (
    <div
      ref={containerRef}
      style={{
        width: 180,
        height: 180,
        borderRadius: '50%',
        position: 'relative',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    />
  );
}
