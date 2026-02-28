import CytoscapeComponent from 'react-cytoscapejs'
import type { NetworkGraph } from '../lib/types'

interface Props {
  graph: NetworkGraph
  onNodeClick?: (npi: string) => void
}

function riskColor(score: number | undefined) {
  if (!score) return '#6b7280'
  if (score >= 70) return '#ef4444'
  if (score >= 40) return '#f59e0b'
  return '#22c55e'
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
        color: n.is_center ? '#3b82f6' : riskColor(n.risk_score),
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
        'color': '#e5e7eb',
        'font-size': 9,
        'text-valign': 'bottom',
        'text-margin-y': 4,
        'border-width': 2,
        'border-color': '#374151',
      },
    },
    {
      selector: 'node[?is_center]',
      style: {
        'border-color': '#60a5fa',
        'border-width': 3,
      },
    },
    {
      selector: 'edge',
      style: {
        'width': 1.5,
        'line-color': '#4b5563',
        'target-arrow-color': '#4b5563',
        'target-arrow-shape': 'triangle',
        'curve-style': 'bezier',
        'opacity': 0.7,
      },
    },
  ]

  return (
    <CytoscapeComponent
      elements={elements}
      stylesheet={stylesheet}
      layout={{ name: 'cose', animate: true, randomize: true }}
      style={{ width: '100%', height: '100%', background: '#030712' }}
      cy={cy => {
        cy.on('tap', 'node', evt => {
          onNodeClick?.(evt.target.id())
        })
      }}
    />
  )
}
