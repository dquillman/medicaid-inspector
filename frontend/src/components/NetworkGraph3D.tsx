import { useMemo, useRef, useState } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls, Line, Billboard, Text } from '@react-three/drei'
import * as THREE from 'three'
import type { NetworkGraph } from '../lib/types'
import { threatColor } from '../lib/threat'
import { dprCap, prefersReducedMotion } from '../lib/webgl'

/**
 * Opt-in 3D force-directed view of a provider's billing network. R3F + drei,
 * lazy-loaded — NEVER the default (the 2D cytoscape stays the workhorse). A
 * small deterministic spring simulation lays the graph out in 3D once per
 * graph; individual meshes (not InstancedMesh) keep hover/click picking simple
 * at this scale (tens-to-low-hundreds of nodes).
 */

const FILAMENT = '#E8B45A'

interface LaidNode {
  id: string
  pos: [number, number, number]
  radius: number
  color: string
  isCenter: boolean
}

function mulberry32(seed: number) {
  let a = seed
  return () => {
    a |= 0; a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/** Cheap 3D spring layout: repulsion (all-pairs) + edge springs, center pinned. */
function layout(graph: NetworkGraph): { nodes: LaidNode[]; edges: [number, number][] } {
  const rnd = mulberry32(0x6d_f1a3)
  const n = graph.nodes.length
  const idx = new Map(graph.nodes.map((nd, i) => [nd.id, i]))
  const maxPaid = Math.max(...graph.nodes.map((nd) => nd.total_paid), 1)

  const pos: number[][] = graph.nodes.map((nd) =>
    nd.is_center ? [0, 0, 0] : [(rnd() - 0.5) * 8, (rnd() - 0.5) * 8, (rnd() - 0.5) * 8],
  )
  const edges: [number, number][] = []
  for (const e of graph.edges) {
    const a = idx.get(e.source); const b = idx.get(e.target)
    if (a != null && b != null) edges.push([a, b])
  }

  const REST = 3.2
  const iterations = n > 160 ? 80 : 140
  for (let it = 0; it < iterations; it++) {
    const force: number[][] = pos.map(() => [0, 0, 0])
    // repulsion
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const dx = pos[i][0] - pos[j][0]
        const dy = pos[i][1] - pos[j][1]
        const dz = pos[i][2] - pos[j][2]
        let d2 = dx * dx + dy * dy + dz * dz
        if (d2 < 0.01) d2 = 0.01
        const f = 12 / d2
        const d = Math.sqrt(d2)
        const ux = dx / d, uy = dy / d, uz = dz / d
        force[i][0] += ux * f; force[i][1] += uy * f; force[i][2] += uz * f
        force[j][0] -= ux * f; force[j][1] -= uy * f; force[j][2] -= uz * f
      }
    }
    // edge springs
    for (const [a, b] of edges) {
      const dx = pos[b][0] - pos[a][0]
      const dy = pos[b][1] - pos[a][1]
      const dz = pos[b][2] - pos[a][2]
      const d = Math.sqrt(dx * dx + dy * dy + dz * dz) || 0.01
      const f = (d - REST) * 0.08
      const ux = dx / d, uy = dy / d, uz = dz / d
      force[a][0] += ux * f; force[a][1] += uy * f; force[a][2] += uz * f
      force[b][0] -= ux * f; force[b][1] -= uy * f; force[b][2] -= uz * f
    }
    const step = 0.85
    for (let i = 0; i < n; i++) {
      if (graph.nodes[i].is_center) continue // pin center at origin
      pos[i][0] += force[i][0] * step
      pos[i][1] += force[i][1] * step
      pos[i][2] += force[i][2] * step
    }
  }

  const nodes: LaidNode[] = graph.nodes.map((nd, i) => ({
    id: nd.id,
    pos: [pos[i][0], pos[i][1], pos[i][2]],
    radius: 0.22 + (nd.total_paid / maxPaid) * 0.7,
    color: nd.is_center ? FILAMENT : threatColor(nd.risk_score ?? 0),
    isCenter: nd.is_center,
  }))
  return { nodes, edges }
}

function Node({ node, onClick }: { node: LaidNode; onClick: () => void }) {
  const [hovered, setHovered] = useState(false)
  const ref = useRef<THREE.Mesh>(null)
  useFrame(() => {
    if (!ref.current) return
    const t = hovered ? 1.35 : 1
    ref.current.scale.lerp(new THREE.Vector3(t, t, t), 0.2)
  })
  return (
    <group position={node.pos}>
      <mesh
        ref={ref}
        onClick={(e) => { e.stopPropagation(); onClick() }}
        onPointerOver={(e) => { e.stopPropagation(); setHovered(true); document.body.style.cursor = 'pointer' }}
        onPointerOut={() => { setHovered(false); document.body.style.cursor = 'auto' }}
      >
        <sphereGeometry args={[node.radius, 24, 24]} />
        <meshStandardMaterial
          color={node.color}
          emissive={node.color}
          emissiveIntensity={node.isCenter ? 0.6 : hovered ? 0.5 : 0.18}
          roughness={0.4}
          metalness={0.1}
        />
      </mesh>
      {(hovered || node.isCenter) && (
        <Billboard position={[0, node.radius + 0.5, 0]}>
          <Text fontSize={0.5} color="#EAF0F8" anchorX="center" anchorY="middle" outlineWidth={0.02} outlineColor="#030712">
            {node.id}
          </Text>
        </Billboard>
      )}
    </group>
  )
}

function Scene({ graph, onNodeClick }: { graph: NetworkGraph; onNodeClick: (npi: string) => void }) {
  const { nodes, edges } = useMemo(() => layout(graph), [graph])
  const reduced = prefersReducedMotion()
  return (
    <>
      <ambientLight intensity={0.6} />
      <pointLight position={[10, 10, 10]} intensity={0.8} />
      <pointLight position={[-10, -6, -10]} intensity={0.3} color={FILAMENT} />
      {edges.map(([a, b], i) => (
        <Line
          key={i}
          points={[nodes[a].pos, nodes[b].pos]}
          color="#9A7B3E"
          opacity={0.35}
          transparent
          lineWidth={1}
        />
      ))}
      {nodes.map((nd) => (
        <Node key={nd.id} node={nd} onClick={() => onNodeClick(nd.id)} />
      ))}
      <OrbitControls
        enablePan={false}
        autoRotate={!reduced}
        autoRotateSpeed={0.6}
        minDistance={5}
        maxDistance={40}
      />
    </>
  )
}

export default function NetworkGraph3D({ graph, onNodeClick }: { graph: NetworkGraph; onNodeClick: (npi: string) => void }) {
  return (
    <Canvas
      dpr={dprCap()}
      camera={{ position: [0, 4, 16], fov: 55 }}
      style={{ width: '100%', height: '100%', background: '#0A0F18' }}
    >
      <Scene graph={graph} onNodeClick={onNodeClick} />
    </Canvas>
  )
}
