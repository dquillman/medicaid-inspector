import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import { getPerfTier, prefersReducedMotion } from '../lib/webgl'

/**
 * The Landing hero: ~6,000 providers as a slow-breathing galactic disc, dim
 * filament for the calm field lerping to arterial red for high risk. ONE
 * draw call (THREE.Points + ShaderMaterial, additive). This is the only WebGL
 * surface in the app and is React.lazy'd — never imported by a data screen.
 *
 * Guards: reduced-motion never mounts this (parent shows a static field);
 * render loop pauses on document.hidden; an FPS sentinel drops pixel ratio
 * then freezes if the GPU can't keep up; pixel ratio is capped by perf tier.
 */

const DIM = new THREE.Color('#9A7B3E')   // filament-dim — calm field
const HOT = new THREE.Color('#D7263D')   // threat-critical — fraud
const STRIDE = 5

function mulberry32(seed: number) {
  let a = seed
  return () => {
    a |= 0; a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/** Deterministic procedural field if the baked bin can't be fetched. */
function proceduralField(count: number): Float32Array {
  const rnd = mulberry32(0x4e4f4354)
  const arr = new Float32Array(count * STRIDE)
  for (let k = 0; k < count; k++) {
    const risk = Math.pow(rnd(), 2.2)
    const r = Math.sqrt(rnd())
    const theta = rnd() * Math.PI * 2 + r * 3
    const rr = r * (1 - risk * 0.25)
    const o = k * STRIDE
    arr[o] = Math.cos(theta) * rr
    arr[o + 1] = (rnd() - 0.5) * 0.14 * (1 - rr * 0.4)
    arr[o + 2] = Math.sin(theta) * rr
    arr[o + 3] = risk
    arr[o + 4] = rnd()
  }
  return arr
}

export default function HeroConstellation() {
  const mountRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const mount = mountRef.current
    if (!mount || prefersReducedMotion()) return

    const tier = getPerfTier()
    const maxPoints = tier === 'low' ? 2500 : tier === 'mid' ? 4500 : 6000
    let dprMax = tier === 'low' ? 1 : tier === 'mid' ? 1.5 : 1.75

    let renderer: THREE.WebGLRenderer
    try {
      renderer = new THREE.WebGLRenderer({ antialias: false, alpha: true, powerPreference: 'low-power' })
    } catch {
      return // WebGL unavailable — parent fallback stands
    }

    let disposed = false
    let raf = 0
    const w = () => mount.clientWidth || 1
    const h = () => mount.clientHeight || 1

    renderer.setPixelRatio(Math.min(window.devicePixelRatio, dprMax))
    renderer.setSize(w(), h())
    renderer.setClearColor(0x000000, 0)
    mount.appendChild(renderer.domElement)
    renderer.domElement.style.width = '100%'
    renderer.domElement.style.height = '100%'

    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(55, w() / h(), 0.1, 100)
    camera.position.set(0, 0.62, 2.25)
    camera.lookAt(0, 0, 0)

    const RADIUS = 1.65
    const material = new THREE.ShaderMaterial({
      uniforms: {
        uTime: { value: 0 },
        uSize: { value: tier === 'low' ? 70 : 95 },
        uDim: { value: new THREE.Vector3(DIM.r, DIM.g, DIM.b) },
        uHot: { value: new THREE.Vector3(HOT.r, HOT.g, HOT.b) },
      },
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      vertexShader: `
        attribute float aRisk;
        attribute float aSeed;
        uniform float uTime;
        uniform float uSize;
        varying float vRisk;
        void main() {
          vRisk = aRisk;
          vec3 p = position;
          float ph = aSeed * 6.2831853;
          p.y += sin(uTime * 0.3 + ph) * 0.02;
          p.x += cos(uTime * 0.2 + ph) * 0.015;
          vec4 mv = modelViewMatrix * vec4(p, 1.0);
          gl_PointSize = uSize * (0.5 + aRisk * 2.3) / max(-mv.z, 0.001);
          gl_Position = projectionMatrix * mv;
        }
      `,
      fragmentShader: `
        precision mediump float;
        varying float vRisk;
        uniform vec3 uDim;
        uniform vec3 uHot;
        void main() {
          vec2 c = gl_PointCoord - 0.5;
          float d = length(c);
          if (d > 0.5) discard;
          float a = smoothstep(0.5, 0.0, d);
          vec3 col = mix(uDim, uHot, vRisk);
          gl_FragColor = vec4(col, a * (0.30 + vRisk * 0.70));
        }
      `,
    })

    const geometry = new THREE.BufferGeometry()
    const points = new THREE.Points(geometry, material)
    points.frustumCulled = false
    scene.add(points)

    const build = (data: Float32Array) => {
      if (disposed) return
      const n = Math.min(maxPoints, Math.floor(data.length / STRIDE))
      const pos = new Float32Array(n * 3)
      const risk = new Float32Array(n)
      const seed = new Float32Array(n)
      for (let k = 0; k < n; k++) {
        const o = k * STRIDE
        pos[k * 3] = data[o] * RADIUS
        pos[k * 3 + 1] = data[o + 1] * RADIUS
        pos[k * 3 + 2] = data[o + 2] * RADIUS
        risk[k] = data[o + 3]
        seed[k] = data[o + 4]
      }
      geometry.setAttribute('position', new THREE.BufferAttribute(pos, 3))
      geometry.setAttribute('aRisk', new THREE.BufferAttribute(risk, 1))
      geometry.setAttribute('aSeed', new THREE.BufferAttribute(seed, 1))
    }

    // Pointer parallax (lerped)
    const target = { x: 0, y: 0 }
    const onPointer = (e: PointerEvent) => {
      const rect = mount.getBoundingClientRect()
      target.x = ((e.clientX - rect.left) / rect.width - 0.5) * 0.12
      target.y = ((e.clientY - rect.top) / rect.height - 0.5) * 0.08
    }
    window.addEventListener('pointermove', onPointer)

    // Resize
    const ro = new ResizeObserver(() => {
      camera.aspect = w() / h()
      camera.updateProjectionMatrix()
      renderer.setSize(w(), h())
    })
    ro.observe(mount)

    // Visibility pause
    let hidden = document.hidden
    const onVis = () => {
      hidden = document.hidden
      if (!hidden && !disposed) loop()
    }
    document.addEventListener('visibilitychange', onVis)

    // FPS sentinel — two-stage degrade
    let frames = 0
    let windowStart = 0
    let degradeStage = 0
    const clock = new THREE.Clock()

    const loop = () => {
      if (disposed || hidden) return
      raf = requestAnimationFrame(loop)
      const t = clock.getElapsedTime()
      material.uniforms.uTime.value = t

      // ease camera toward pointer target
      camera.position.x += (target.x - camera.position.x) * 0.04
      camera.position.y += (0.62 + target.y - camera.position.y) * 0.04
      camera.lookAt(0, 0, 0)
      renderer.render(scene, camera)

      // sentinel: sample fps over 2s windows
      frames++
      if (windowStart === 0) windowStart = t
      else if (t - windowStart >= 2) {
        const fps = frames / (t - windowStart)
        frames = 0; windowStart = t
        if (fps < 40 && degradeStage === 0) {
          degradeStage = 1
          dprMax = 1
          renderer.setPixelRatio(1)
        } else if (fps < 30 && degradeStage === 1) {
          degradeStage = 2
          // give up animating — render one last frame and stop
          cancelAnimationFrame(raf)
        }
      }
    }

    // Load baked data, fall back to procedural
    fetch('/constellation.bin')
      .then((r) => (r.ok ? r.arrayBuffer() : Promise.reject(new Error('no bin'))))
      .then((buf) => build(new Float32Array(buf)))
      .catch(() => build(proceduralField(maxPoints)))
      .finally(() => { if (!disposed) loop() })

    return () => {
      disposed = true
      cancelAnimationFrame(raf)
      window.removeEventListener('pointermove', onPointer)
      document.removeEventListener('visibilitychange', onVis)
      ro.disconnect()
      geometry.dispose()
      material.dispose()
      renderer.dispose()
      if (renderer.domElement.parentNode === mount) mount.removeChild(renderer.domElement)
    }
  }, [])

  return <div ref={mountRef} aria-hidden="true" className="absolute inset-0" />
}
