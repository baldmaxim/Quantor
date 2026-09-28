'use client';

import type { CalcSystemEdge, CalcSystemGraph, CalcSystemNode } from '@quantor/api-client';

import { Button, StatusBadge } from '@/components/ui';
import { PROVENANCE, UNRESOLVED_TITLES, cardinalityText } from '@/lib/calc/synthesis';

/**
 * Логическая структура системы деревом: кто с кем связан, откуда каждый элемент и какая у него
 * кратность. Это не чертёж и не трасса — координат здесь нет. Ниже — что Quantor пока не знает.
 */

interface ISystemStructureProps {
  graph: CalcSystemGraph;
  onExplain: (elementId: string) => void;
}

const NodeRow = ({
  node,
  via,
  onExplain,
}: {
  node: CalcSystemNode;
  via?: CalcSystemEdge;
  onExplain: (elementId: string) => void;
}) => {
  const provenance = PROVENANCE[node.provenance];
  return (
    <div className="flex flex-wrap items-center gap-x-[var(--s-3)] gap-y-[var(--s-1)] rounded-[var(--radius-sm)] border border-border bg-surface px-[var(--s-4)] py-[var(--s-3)] text-sm">
      {via && (
        <span className="basis-full text-xs text-muted">
          ↳ {via.title} · {PROVENANCE[via.provenance].label}
        </span>
      )}
      <span className="font-medium wrap-anywhere">{node.title}</span>
      <StatusBadge tone={provenance.tone}>{provenance.label}</StatusBadge>
      <span className="tabular text-muted">{cardinalityText(node)}</span>
      <span className="font-mono text-xs text-muted">{node.semantic_type}</span>
      <Button compact onClick={() => onExplain(node.id)}>
        Почему?
      </Button>
    </div>
  );
};

const Branch = ({
  node,
  via,
  graph,
  seen,
  onExplain,
}: {
  node: CalcSystemNode;
  via?: CalcSystemEdge;
  graph: CalcSystemGraph;
  seen: ReadonlySet<string>;
  onExplain: (elementId: string) => void;
}) => {
  const next = new Set(seen).add(node.id);
  const outgoing = (graph.edges ?? []).filter(
    (edge) => edge.source_node === node.id && !next.has(edge.target_node),
  );
  return (
    <li className="flex flex-col gap-[var(--s-2)]">
      <NodeRow node={node} via={via} onExplain={onExplain} />
      {outgoing.length > 0 && (
        <ul className="ml-[var(--s-5)] flex list-none flex-col gap-[var(--s-2)] border-l border-border pl-[var(--s-4)]">
          {outgoing.map((edge) => {
            const target = graph.nodes.find((item) => item.id === edge.target_node);
            return target ? (
              <Branch
                key={edge.id}
                node={target}
                via={edge}
                graph={graph}
                seen={next}
                onExplain={onExplain}
              />
            ) : null;
          })}
        </ul>
      )}
    </li>
  );
};

export const SystemStructure = ({ graph, onExplain }: ISystemStructureProps) => {
  const edges = graph.edges ?? [];
  const targets = new Set(edges.map((edge) => edge.target_node));
  const linked = new Set(edges.flatMap((edge) => [edge.source_node, edge.target_node]));
  const roots = graph.nodes.filter((node) => linked.has(node.id) && !targets.has(node.id));
  const loose = graph.nodes.filter((node) => !linked.has(node.id));
  const unknown = graph.unresolved ?? [];

  return (
    <div className="flex flex-col gap-[var(--s-5)]">
      {roots.length > 0 && (
        <ul className="flex list-none flex-col gap-[var(--s-2)]">
          {roots.map((node) => (
            <Branch
              key={node.id}
              node={node}
              graph={graph}
              seen={new Set()}
              onExplain={onExplain}
            />
          ))}
        </ul>
      )}
      {loose.length > 0 && (
        <section className="flex flex-col gap-[var(--s-2)]">
          <h3 className="text-sm font-medium">Элементы без установленных связей</h3>
          <ul className="flex list-none flex-col gap-[var(--s-2)]">
            {loose.map((node) => (
              <li key={node.id}>
                <NodeRow node={node} onExplain={onExplain} />
              </li>
            ))}
          </ul>
        </section>
      )}
      <section className="flex flex-col gap-[var(--s-2)]">
        <h3 className="text-sm font-medium">Что Quantor пока не знает</h3>
        {unknown.length === 0 ? (
          <p className="text-sm text-muted">Открытых вопросов нет.</p>
        ) : (
          <ul className="flex list-none flex-col gap-[var(--s-2)]">
            {unknown.map((item) => (
              <li key={item.key} className="flex flex-col gap-[var(--s-1)] text-sm">
                <span className="flex flex-wrap items-center gap-[var(--s-2)]">
                  <StatusBadge tone={item.structural ? 'warning' : 'neutral'}>
                    {UNRESOLVED_TITLES[item.kind]}
                  </StatusBadge>
                  <span className="font-medium wrap-anywhere">{item.title}</span>
                </span>
                <span className="text-muted wrap-anywhere">
                  Известно: {item.known}. Нужно: {item.needed}.
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
};
