import CytoscapeComponent from 'react-cytoscapejs'
import type { NetworkGraph } from '../lib/types'
import { threatColor } from '../lib/threat'

interface Props {
  graph: NetworkGraph
  onNodeClick?: (npi: string) => void
}

export default function NetworkGraphCanvas({ graph, onNodeClick }: Props) {
  const maxPaid = Math.max(...graph.nodes.map(n => n.total_paid), 1)

  const elements = [
    ...graph.nodes.map(n => ({
      data: {
        id: n.id,
        label: n.id,
        total_paid: n.total_paid,
        is_center: n.is_center,
        size: 20 + (n.total_paid / maxPaid) * 60,
        // center = the lamp (filament); others on the continuous threat ramp
        color: n.is_center ? '#E8B45A' : threatColor(n.risk_score ?? 0),
      },
    })),
    ...graph.edges.map((e, i) => ({
      data: {
        id: `e${i}`,
        source: e.source,
        target: e.target,
        weight: e.weight,
        label: e.claim_count.toString(),
      },
    })),
  ]

  const stylesheet: any[] = [
    {
      selector: 'node',
      style: {
        'background-color': 'data(color)',
        'width': 'data(size)',
        'height': 'data(size)',
        'label': 'data(label)',
        'color': '#AEBACA',
        'font-family': 'IBM Plex Mono, monospace',
        'font-size': 9,
        'text-valign': 'bottom',
        'text-margin-y': 4,
        'border-width': 1.5,
        'border-color': '#1C2636',
      },
    },
    {
      selector: 'node[?is_center]',
      style: {
        'border-color': '#E8B45A',
        'border-width': 3,
      },
    },
    {
      // acquired target — filament reticle glow
      selector: 'node:selected',
      style: {
        'border-color': '#E8B45A',
        'border-width': 3,
        'overlay-color': '#E8B45A',
        'overlay-opacity': 0.12,
        'overlay-padding': 6,
      },
    },
    {
      selector: 'edge',
      style: {
        'width': 1.2,
        'line-color': '#9A7B3E',
        'target-arrow-color': '#9A7B3E',
        'target-arrow-shape': 'triangle',
        'curve-style': 'bezier',
        'opacity': 0.45,
      },
    },
  ]

  return (
    <CytoscapeComponent
      elements={elements}
      stylesheet={stylesheet}
      layout={{ name: 'cose', animate: true, randomize: true }}
      style={{ width: '100%', height: '100%', background: '#0A0F18' }}
      cy={cy => {
        cy.on('tap', 'node', evt => {
          onNodeClick?.(evt.target.id())
        })
      }}
    />
  )
}
