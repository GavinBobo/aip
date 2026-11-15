// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import {
	forwardRef,
	useCallback,
	useEffect,
	useImperativeHandle,
	useRef,
	useState,
	type PointerEvent as ReactPointerEvent,
} from 'react';

import {
	bezierPath,
	CARD_WIDTH,
	columnPort,
	MAX_ZOOM,
	MIN_ZOOM,
	nodeHeight,
	nodesBounds,
	screenToWorld,
	zoomAtPoint,
	type Point,
} from '@/lib/erd/geometry';
import type { ErdNode, ErdRelationship, ErdViewport } from '@/types/erd';
import type { ErdNote } from '@/types/erd';
import type { ErdArea } from '@/types/erd';
import { AreaCard } from './AreaCard';
import { Minimap } from './Minimap';
import { NoteCard } from './NoteCard';
import { RelationshipEdge } from './RelationshipEdge';
import { TableCard } from './TableCard';

export type ErdCanvasHandle = {
	zoomIn: () => void;
	zoomOut: () => void;
	fit: () => void;
};

export type ColumnConnection = {
	nodeId: string;
	column: string | null;
};

type ErdCanvasProps = {
	nodes: ErdNode[];
	relationships: ErdRelationship[];
	viewport: ErdViewport;
	readOnly: boolean;
	search: string;
	selectedRelationshipId: string | null;
	selectedNodeIds: ReadonlySet<string>;
	notes: ErdNote[];
	areas: ErdArea[];
	snapToGrid: boolean;
	showMinimap: boolean;
	onViewportChange: (viewport: ErdViewport) => void;
	onNodeSelect: (nodeId: string, additive: boolean) => void;
	onClearSelection: () => void;
	onNodesMove: (updates: { id: string; x: number; y: number }[]) => void;
	onNodeDragStart: () => void;
	onNodesMoveEnd: (nodeIds: string[]) => void;
	onToggleCollapse: (nodeId: string) => void;
	onEditNode: (nodeId: string) => void;
	onDeleteNode: (nodeId: string) => void;
	onConnect: (source: ColumnConnection, target: ColumnConnection) => void;
	onSelectRelationship: (id: string | null) => void;
	onNoteDragStart: () => void;
	onNoteMove: (noteId: string, x: number, y: number) => void;
	onNoteMoveEnd: (noteId: string) => void;
	onNoteTextChange: (noteId: string, text: string) => void;
	onNoteTextCommit: (noteId: string) => void;
	onNoteDelete: (noteId: string) => void;
	onAreaDragStart: () => void;
	onAreaMove: (areaId: string, x: number, y: number) => void;
	onAreaMoveEnd: (areaId: string) => void;
	onAreaResize: (areaId: string, width: number, height: number) => void;
	onAreaResizeEnd: (areaId: string) => void;
	onAreaRename: (areaId: string, name: string) => void;
	onAreaDelete: (areaId: string) => void;
};

type AreaDrag = {
	areaId: string;
	clientX: number;
	clientY: number;
	startX: number;
	startY: number;
	zoom: number;
	origins: { id: string; x: number; y: number }[];
};

type AreaResize = {
	areaId: string;
	clientX: number;
	clientY: number;
	startWidth: number;
	startHeight: number;
	zoom: number;
};

type NoteDrag = {
	noteId: string;
	clientX: number;
	clientY: number;
	startX: number;
	startY: number;
	zoom: number;
};

type NodeDrag = {
	clientX: number;
	clientY: number;
	zoom: number;
	origins: { id: string; x: number; y: number }[];
};

type PanDrag = {
	clientX: number;
	clientY: number;
	startX: number;
	startY: number;
};

type ConnectDrag = {
	source: ColumnConnection;
	from: Point;
};

const GRID_SIZE = 22;

export const ErdCanvas = forwardRef<ErdCanvasHandle, ErdCanvasProps>(
	(
		{
			nodes,
			relationships,
			viewport,
			readOnly,
			search,
			selectedRelationshipId,
			selectedNodeIds,
			notes,
			areas,
			snapToGrid,
			showMinimap,
			onViewportChange,
			onNodeSelect,
			onClearSelection,
			onNodesMove,
			onNodeDragStart,
			onNodesMoveEnd,
			onToggleCollapse,
			onEditNode,
			onDeleteNode,
			onConnect,
			onSelectRelationship,
			onNoteDragStart,
			onNoteMove,
			onNoteMoveEnd,
			onNoteTextChange,
			onNoteTextCommit,
			onNoteDelete,
			onAreaDragStart,
			onAreaMove,
			onAreaMoveEnd,
			onAreaResize,
			onAreaResizeEnd,
			onAreaRename,
			onAreaDelete,
		},
		ref,
	) => {
		const containerRef = useRef<HTMLDivElement | null>(null);
		const nodeDrag = useRef<NodeDrag | null>(null);
		const panDrag = useRef<PanDrag | null>(null);
		const connectDrag = useRef<ConnectDrag | null>(null);
		const noteDrag = useRef<NoteDrag | null>(null);
		const areaDrag = useRef<AreaDrag | null>(null);
		const areaResize = useRef<AreaResize | null>(null);
		const [rubberBand, setRubberBand] = useState<{ from: Point; to: Point } | null>(null);
		// Click-to-connect: the first click arms a column, the second one finishes
		// the line. Dragging works too, but a click pair is easier on a trackpad.
		const [armed, setArmed] = useState<ColumnConnection | null>(null);
		const [containerSize, setContainerSize] = useState({ width: 0, height: 0 });

		// A snapped drag lands every card on the 20px lattice; the absolute
		// position is rounded (not the delta) so repeated drags cannot drift.
		const snapRef = useRef(snapToGrid);
		useEffect(() => {
			snapRef.current = snapToGrid;
		}, [snapToGrid]);
		const snap = (value: number) => (snapRef.current ? Math.round(value / 20) * 20 : value);

		const handlers = useRef({
			onViewportChange,
			onNodesMove,
			onNodesMoveEnd,
			onNoteMove,
			onNoteMoveEnd,
			onAreaMove,
			onAreaMoveEnd,
			onAreaResize,
			onAreaResizeEnd,
			onConnect,
		});

		const viewportRef = useRef(viewport);
		const nodesRef = useRef(nodes);
		const areasRef = useRef(areas);
		const notesRef = useRef(notes);

		useEffect(() => {
			handlers.current = {
				onViewportChange,
				onNodesMove,
				onNodesMoveEnd,
				onNoteMove,
				onNoteMoveEnd,
				onAreaMove,
				onAreaMoveEnd,
				onAreaResize,
				onAreaResizeEnd,
				onConnect,
			};
		}, [
			onViewportChange,
			onNodesMove,
			onNodesMoveEnd,
			onNoteMove,
			onNoteMoveEnd,
			onAreaMove,
			onAreaMoveEnd,
			onAreaResize,
			onAreaResizeEnd,
			onConnect,
		]);

		useEffect(() => {
			viewportRef.current = viewport;
		}, [viewport]);

		useEffect(() => {
			nodesRef.current = nodes;
		}, [nodes]);

		useEffect(() => {
			areasRef.current = areas;
		}, [areas]);

		useEffect(() => {
			notesRef.current = notes;
		}, [notes]);

		useEffect(() => {
			const element = containerRef.current;
			if (!element) return undefined;
			const update = () =>
				setContainerSize({
					width: element.clientWidth,
					height: element.clientHeight,
				});
			update();
			const observer = new ResizeObserver(update);
			observer.observe(element);
			return () => observer.disconnect();
		}, []);

		useEffect(() => {
			const onKey = (event: KeyboardEvent) => {
				if (event.key === 'Escape') setArmed(null);
			};
			window.addEventListener('keydown', onKey);
			return () => window.removeEventListener('keydown', onKey);
		}, []);

		const fit = useCallback(() => {
			const element = containerRef.current;
			const base = nodesBounds(nodesRef.current);
			// Areas and notes are part of the drawing: fitting to the cards
			// alone would leave a region added below the diagram off screen.
			const rects = [
				...(base ? [base] : []),
				...areasRef.current.map((area) => ({
					minX: area.x,
					minY: area.y,
					maxX: area.x + area.width,
					maxY: area.y + area.height,
				})),
				...notesRef.current.map((note) => ({
					minX: note.x,
					minY: note.y,
					maxX: note.x + note.width,
					maxY: note.y + note.height,
				})),
			];
			if (!element || rects.length === 0) return;
			const bounds = rects.reduce((acc, rect) => ({
				minX: Math.min(acc.minX, rect.minX),
				minY: Math.min(acc.minY, rect.minY),
				maxX: Math.max(acc.maxX, rect.maxX),
				maxY: Math.max(acc.maxY, rect.maxY),
			}));
			const width = element.clientWidth;
			const height = element.clientHeight;
			const contentWidth = Math.max(bounds.maxX - bounds.minX, 1);
			const contentHeight = Math.max(bounds.maxY - bounds.minY, 1);
			const zoom = Math.min(
				MAX_ZOOM,
				Math.max(
					MIN_ZOOM,
					Math.min((width - 80) / contentWidth, (height - 80) / contentHeight),
				),
			);
			handlers.current.onViewportChange({
				zoom,
				x: (width - contentWidth * zoom) / 2 - bounds.minX * zoom,
				y: (height - contentHeight * zoom) / 2 - bounds.minY * zoom,
			});
		}, []);

		const zoomBy = useCallback((factor: number) => {
			const element = containerRef.current;
			if (!element) return;
			const anchor = { x: element.clientWidth / 2, y: element.clientHeight / 2 };
			handlers.current.onViewportChange(
				zoomAtPoint(viewportRef.current, viewportRef.current.zoom * factor, anchor),
			);
		}, []);

		useImperativeHandle(ref, () => ({
			zoomIn: () => zoomBy(1.25),
			zoomOut: () => zoomBy(0.8),
			fit,
		}));

		// Finish every gesture on `window`: the pointer may leave the card it
		// started on, and a captured pointer would otherwise stop reporting.
		useEffect(() => {
			const world = (event: PointerEvent): Point => {
				const element = containerRef.current;
				if (!element) return { x: 0, y: 0 };
				const rect = element.getBoundingClientRect();
				return screenToWorld(
					{ x: event.clientX - rect.left, y: event.clientY - rect.top },
					viewportRef.current,
				);
			};

			const onMove = (event: PointerEvent) => {
				if (panDrag.current) {
					handlers.current.onViewportChange({
						...viewportRef.current,
						x: panDrag.current.startX + (event.clientX - panDrag.current.clientX),
						y: panDrag.current.startY + (event.clientY - panDrag.current.clientY),
					});
				} else if (nodeDrag.current) {
					const drag = nodeDrag.current;
					const dx = (event.clientX - drag.clientX) / drag.zoom;
					const dy = (event.clientY - drag.clientY) / drag.zoom;
					handlers.current.onNodesMove(
						drag.origins.map((origin) => ({
							id: origin.id,
							x: snap(origin.x + dx),
							y: snap(origin.y + dy),
						})),
					);
				} else if (connectDrag.current) {
					setRubberBand({ from: connectDrag.current.from, to: world(event) });
				} else if (noteDrag.current) {
					const drag = noteDrag.current;
					handlers.current.onNoteMove(
						drag.noteId,
						drag.startX + (event.clientX - drag.clientX) / drag.zoom,
						drag.startY + (event.clientY - drag.clientY) / drag.zoom,
					);
				} else if (areaDrag.current) {
					const drag = areaDrag.current;
					const dx = (event.clientX - drag.clientX) / drag.zoom;
					const dy = (event.clientY - drag.clientY) / drag.zoom;
					handlers.current.onAreaMove(
						drag.areaId,
						snap(drag.startX + dx),
						snap(drag.startY + dy),
					);
					if (drag.origins.length > 0) {
						handlers.current.onNodesMove(
							drag.origins.map((origin) => ({
								id: origin.id,
								x: snap(origin.x + dx),
								y: snap(origin.y + dy),
							})),
						);
					}
				} else if (areaResize.current) {
					const drag = areaResize.current;
					handlers.current.onAreaResize(
						drag.areaId,
						snap(drag.startWidth + (event.clientX - drag.clientX) / drag.zoom),
						snap(drag.startHeight + (event.clientY - drag.clientY) / drag.zoom),
					);
				}
			};

			const onUp = (event: PointerEvent) => {
				if (nodeDrag.current) {
					handlers.current.onNodesMoveEnd(
						nodeDrag.current.origins.map((origin) => origin.id),
					);
					nodeDrag.current = null;
				}
				panDrag.current = null;
				if (noteDrag.current) {
					handlers.current.onNoteMoveEnd(noteDrag.current.noteId);
					noteDrag.current = null;
				}
				if (areaDrag.current) {
					handlers.current.onAreaMoveEnd(areaDrag.current.areaId);
					if (areaDrag.current.origins.length > 0) {
						handlers.current.onNodesMoveEnd(
							areaDrag.current.origins.map((origin) => origin.id),
						);
					}
					areaDrag.current = null;
				}
				if (areaResize.current) {
					handlers.current.onAreaResizeEnd(areaResize.current.areaId);
					areaResize.current = null;
				}

				if (connectDrag.current) {
					const target = document
						.elementFromPoint(event.clientX, event.clientY)
						?.closest('[data-erd-column]');
					const nodeId = target?.getAttribute('data-erd-node');
					const column = target?.getAttribute('data-erd-column');
					const source = connectDrag.current.source;
					connectDrag.current = null;
					setRubberBand(null);
					if (
						nodeId &&
						column &&
						(nodeId !== source.nodeId || column !== source.column)
					) {
						handlers.current.onConnect(source, { nodeId, column });
					}
				}
			};

			window.addEventListener('pointermove', onMove);
			window.addEventListener('pointerup', onUp);
			window.addEventListener('pointercancel', onUp);
			return () => {
				window.removeEventListener('pointermove', onMove);
				window.removeEventListener('pointerup', onUp);
				window.removeEventListener('pointercancel', onUp);
			};
		}, []);

		const onWheel = (event: React.WheelEvent) => {
			event.preventDefault();
			const element = containerRef.current;
			if (!element) return;
			const rect = element.getBoundingClientRect();
			const anchor = { x: event.clientX - rect.left, y: event.clientY - rect.top };
			if (event.ctrlKey || event.metaKey) {
				const factor = Math.exp(-event.deltaY / 400);
				onViewportChange(zoomAtPoint(viewport, viewport.zoom * factor, anchor));
			} else {
				onViewportChange({
					...viewport,
					x: viewport.x - event.deltaX,
					y: viewport.y - event.deltaY,
				});
			}
		};

		const onBackgroundPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
			if (event.button !== 0) return;
			if (
				(event.target as HTMLElement).closest(
					'[data-erd-node], [data-erd-note], [data-erd-area]',
				)
			) {
				return;
			}
			onSelectRelationship(null);
			onClearSelection();
			panDrag.current = {
				clientX: event.clientX,
				clientY: event.clientY,
				startX: viewport.x,
				startY: viewport.y,
			};
		};

		const onHeaderPointerDown = (event: ReactPointerEvent, nodeId: string) => {
			if (event.button !== 0) return;
			event.stopPropagation();
			const node = nodes.find((row) => row.id === nodeId);
			if (!node) return;
			const additive = event.shiftKey || event.metaKey || event.ctrlKey;
			if (additive) {
				onNodeSelect(nodeId, true);
				return;
			}
			// Dragging a card outside the selection replaces it; dragging one
			// inside the selection moves the whole group.
			const origins = selectedNodeIds.has(nodeId)
				? nodes.filter((row) => selectedNodeIds.has(row.id))
				: [node];
			if (!selectedNodeIds.has(nodeId)) onNodeSelect(nodeId, false);
			onNodeDragStart();
			nodeDrag.current = {
				clientX: event.clientX,
				clientY: event.clientY,
				zoom: viewport.zoom,
				origins: origins.map((row) => ({ id: row.id, x: row.x, y: row.y })),
			};
		};

		const onColumnPointerDown = (event: ReactPointerEvent, nodeId: string, column: string) => {
			if (event.button !== 0) return;
			event.stopPropagation();
			event.preventDefault();
			const node = nodes.find((row) => row.id === nodeId);
			if (!node) return;
			const side = columnPort(node, column, 'right').x > node.x + 1 ? 'right' : 'left';
			const from = columnPort(node, column, side);
			connectDrag.current = { source: { nodeId, column }, from };
			setRubberBand({ from, to: from });
		};

		const onNotePointerDown = (event: ReactPointerEvent, noteId: string) => {
			if (event.button !== 0) return;
			event.stopPropagation();
			const note = notes.find((row) => row.id === noteId);
			if (!note) return;
			onNoteDragStart();
			noteDrag.current = {
				noteId,
				clientX: event.clientX,
				clientY: event.clientY,
				startX: note.x,
				startY: note.y,
				zoom: viewport.zoom,
			};
		};

		const onAreaPointerDown = (event: ReactPointerEvent, areaId: string) => {
			if (event.button !== 0) return;
			event.stopPropagation();
			const area = areas.find((row) => row.id === areaId);
			if (!area) return;
			// Capture membership now: a node dragged into the rectangle later
			// should not teleport on the next frame.
			const origins = nodes
				.filter((node) => {
					const centreX = node.x + CARD_WIDTH / 2;
					const centreY = node.y + nodeHeight(node) / 2;
					return (
						centreX >= area.x &&
						centreX <= area.x + area.width &&
						centreY >= area.y &&
						centreY <= area.y + area.height
					);
				})
				.map((node) => ({ id: node.id, x: node.x, y: node.y }));
			onAreaDragStart();
			areaDrag.current = {
				areaId,
				clientX: event.clientX,
				clientY: event.clientY,
				startX: area.x,
				startY: area.y,
				zoom: viewport.zoom,
				origins,
			};
		};

		const onAreaResizeStart = (event: ReactPointerEvent, areaId: string) => {
			if (event.button !== 0) return;
			const area = areas.find((row) => row.id === areaId);
			if (!area) return;
			onAreaDragStart();
			areaResize.current = {
				areaId,
				clientX: event.clientX,
				clientY: event.clientY,
				startWidth: area.width,
				startHeight: area.height,
				zoom: viewport.zoom,
			};
		};

		const onColumnClick = useCallback(
			(nodeId: string, column: string) => {
				if (readOnly) return;
				if (armed && (armed.nodeId !== nodeId || armed.column !== column)) {
					onConnect(armed, { nodeId, column });
					setArmed(null);
					return;
				}
				setArmed({ nodeId, column });
			},
			[armed, onConnect, readOnly],
		);

		const nodeById = new Map(nodes.map((node) => [node.id, node]));
		const needle = search.trim().toLowerCase();
		const isDimmed = (node: ErdNode) =>
			needle.length > 0 &&
			!node.name.toLowerCase().includes(needle) &&
			!node.columns.some((column) => column.name.toLowerCase().includes(needle));

		const dotSize = Math.max(8, GRID_SIZE * viewport.zoom);

		return (
			<div
				ref={containerRef}
				className="relative h-full w-full touch-none overflow-hidden bg-[#fafafa] dark:bg-zinc-950"
				style={{
					backgroundImage:
						'radial-gradient(circle, rgba(113,113,122,0.35) 1px, transparent 1px)',
					backgroundSize: `${dotSize}px ${dotSize}px`,
					backgroundPosition: `${viewport.x}px ${viewport.y}px`,
				}}
				onPointerDown={onBackgroundPointerDown}
				onWheel={onWheel}
			>
				<div
					className="absolute left-0 top-0 origin-top-left"
					style={{
						transform: `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.zoom})`,
					}}
				>
					<svg
						className="pointer-events-none absolute left-0 top-0 overflow-visible"
						width={1}
						height={1}
					>
						<g className="pointer-events-auto">
							{relationships.map((relationship) => {
								const source = nodeById.get(relationship.source_node_id);
								const target = nodeById.get(relationship.target_node_id);
								if (!source || !target) return null;
								return (
									<RelationshipEdge
										key={relationship.id}
										relationship={relationship}
										source={source}
										target={target}
										selected={relationship.id === selectedRelationshipId}
										onSelect={onSelectRelationship}
									/>
								);
							})}
							{rubberBand && (
								<path
									d={bezierPath(rubberBand.from, rubberBand.to)}
									fill="none"
									stroke="#76b900"
									strokeWidth={2}
									strokeDasharray="6 4"
								/>
							)}
						</g>
					</svg>
					{areas.map((area) => (
						<AreaCard
							key={area.id}
							area={area}
							readOnly={readOnly}
							onDragStart={onAreaPointerDown}
							onResizeStart={onAreaResizeStart}
							onRename={onAreaRename}
							onDelete={onAreaDelete}
						/>
					))}
					{nodes.map((node) => (
						<TableCard
							key={node.id}
							node={node}
							dimmed={isDimmed(node)}
							selected={selectedNodeIds.has(node.id)}
							readOnly={readOnly}
							onHeaderPointerDown={onHeaderPointerDown}
							onColumnPointerDown={onColumnPointerDown}
							onColumnClick={onColumnClick}
							armedColumn={armed?.nodeId === node.id ? armed.column : null}
							onToggleCollapse={onToggleCollapse}
							onEdit={onEditNode}
							onDelete={onDeleteNode}
						/>
					))}
					{notes.map((note) => (
						<NoteCard
							key={note.id}
							note={note}
							readOnly={readOnly}
							onDragStart={onNotePointerDown}
							onTextChange={onNoteTextChange}
							onTextCommit={onNoteTextCommit}
							onDelete={onNoteDelete}
						/>
					))}
				</div>
				{showMinimap && containerSize.width > 0 && (
					<Minimap
						nodes={nodes}
						areas={areas}
						notes={notes}
						viewport={viewport}
						containerWidth={containerSize.width}
						containerHeight={containerSize.height}
						onNavigate={(world) =>
							handlers.current.onViewportChange({
								...viewportRef.current,
								x: containerSize.width / 2 - world.x * viewportRef.current.zoom,
								y: containerSize.height / 2 - world.y * viewportRef.current.zoom,
							})
						}
					/>
				)}
			</div>
		);
	},
);

ErdCanvas.displayName = 'ErdCanvas';
