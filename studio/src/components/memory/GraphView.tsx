import { useEffect, useRef, useCallback } from 'react'
import * as d3 from 'd3'
import type { MemoryNode, MemoryEdge } from '@/types/memory'

interface GraphViewProps {
  nodes: MemoryNode[]
  edges: MemoryEdge[]
  onSelectEvent: (eventId: string) => void
}

interface D3Node extends d3.SimulationNodeDatum {
  id: string
  core_intent: string
  event_kind: string
  relevance_score: number
  is_active: boolean
  is_dormant: boolean
}

interface D3Link extends d3.SimulationLinkDatum<D3Node> {
  source: string
  target: string
  weight: number
  link_kind?: string
}

export function GraphView({ nodes, edges, onSelectEvent }: GraphViewProps) {
  const svgRef = useRef<SVGSVGElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const onSelectEventRef = useRef(onSelectEvent)
  const positionsRef = useRef<Record<string, { x: number; y: number }>>({})
  onSelectEventRef.current = onSelectEvent

  const draw = useCallback(() => {
    if (!svgRef.current || !containerRef.current || nodes.length === 0) return

    const width = containerRef.current.clientWidth
    const height = containerRef.current.clientHeight

    d3.select(svgRef.current).selectAll('*').remove()

    const svg = d3
      .select(svgRef.current)
      .attr('width', width)
      .attr('height', height)

    const g = svg.append('g')

    const d3Nodes: D3Node[] = nodes.map((n) => ({
      ...n,
      x: positionsRef.current[n.id]?.x ?? width / 2 + (Math.random() - 0.5) * 100,
      y: positionsRef.current[n.id]?.y ?? height / 2 + (Math.random() - 0.5) * 100,
    }))

    const nodeIds = new Set(d3Nodes.map((n) => n.id))
    const d3Links: D3Link[] = edges
      .filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target))
      .map((e) => ({
        source: e.source,
        target: e.target,
        weight: e.weight,
        link_kind: e.link_kind,
      }))

    const link = g
      .append('g')
      .attr('class', 'links')
      .selectAll('line')
      .data(d3Links)
      .join('line')
      .attr('stroke', (d) => (d.link_kind === 'mention' ? '#f59e0b' : '#333333'))
      .attr('stroke-opacity', (d) => (d.link_kind === 'mention' ? 0.8 : 0.6))
      .attr('stroke-dasharray', (d) => (d.link_kind === 'mention' ? '4 4' : 'none'))
      .attr('stroke-width', (d) => Math.max(0.5, Math.min(3, d.weight * 4)))

    const node = g
      .append('g')
      .attr('class', 'nodes')
      .selectAll('circle')
      .data(d3Nodes)
      .join('circle')
      .attr('r', (d) => {
        const base = d.is_active ? 14 : 10
        const scale = 0.5 + (d.relevance_score ?? 0.5)
        return Math.min(18, Math.max(8, base * scale))
      })
      .attr('fill', (d) => {
        if (d.event_kind === 'summary') return '#8b5cf6'
        if (d.is_active) return '#3b82f6'
        return '#4b5563'
      })
      .attr('opacity', (d) => (d.is_dormant ? 0.6 : 1))
      .attr('cursor', 'pointer')
      .attr('stroke', '#1a1a1a')
      .attr('stroke-width', 1)

    const simulation = d3
      .forceSimulation<D3Node>(d3Nodes)
      .force(
        'link',
        d3
          .forceLink<D3Node, D3Link>(d3Links)
          .id((d) => d.id)
          .strength((d) => (d.weight ?? 0.5) * 0.3)
      )
      .force('charge', d3.forceManyBody().strength(-200))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide<D3Node>().radius(30))

    const dragBehavior = d3
      .drag<SVGCircleElement, D3Node>()
      .on('start', (event, d) => {
        if (!event.active) simulation.alphaTarget(0.3).restart()
        d.fx = d.x
        d.fy = d.y
      })
      .on('drag', (event, d) => {
        d.fx = event.x
        d.fy = event.y
      })
      .on('end', (event, _d) => {
        if (!event.active) simulation.alphaTarget(0)
        // Keep node pinned at dragged position so it doesn't drift on redraw
      })

    node
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .call(dragBehavior as any)
      .on('click', (_, d) => onSelectEventRef.current(d.id))
      .append('title')
      .text((d) => d.core_intent || d.id)

    simulation.on('tick', () => {
      d3Nodes.forEach((d) => {
        if (d.x != null && d.y != null) positionsRef.current[d.id] = { x: d.x, y: d.y }
      })

      link
        .attr('x1', (d) => ((d.source as unknown) as D3Node).x ?? 0)
        .attr('y1', (d) => ((d.source as unknown) as D3Node).y ?? 0)
        .attr('x2', (d) => ((d.target as unknown) as D3Node).x ?? 0)
        .attr('y2', (d) => ((d.target as unknown) as D3Node).y ?? 0)

      node.attr('cx', (d) => d.x ?? 0).attr('cy', (d) => d.y ?? 0)
    })

    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 4])
      .on('zoom', (event) => g.attr('transform', event.transform))

    svg.call(zoom)
  }, [nodes, edges])

  useEffect(() => {
    draw()
  }, [draw])

  useEffect(() => {
    const ro = new ResizeObserver(draw)
    if (containerRef.current) ro.observe(containerRef.current)
    return () => ro.disconnect()
  }, [draw])

  if (nodes.length === 0) return null

  return (
    <div ref={containerRef} className="w-full h-full min-h-[400px]">
      <svg ref={svgRef} className="w-full h-full" />
    </div>
  )
}
