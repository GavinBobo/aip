// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';

import { erdApi } from '@/api/erd';
import { useSession } from '@/auth/auth-client';
import { Button } from '@/common/Button';
import { EmptyState } from '@/common/EmptyState';
import { Spinner } from '@/common/Spinner';
import { ButtonTheme, Size } from '@/enums/button';
import { t } from '@/i18n';
import type { ErdClipboard } from '@/lib/erd/clipboard';
import { readClipboard, writeClipboard } from '@/lib/erd/clipboard';
import { downloadText } from '@/lib/erd/download';
import type { CanvasSnapshot } from '@/lib/erd/history';
import { CanvasHistory } from '@/lib/erd/history';
import { gridLayout, layeredLayout } from '@/lib/erd/layout';
import { moveItem } from '@/lib/erd/ordering';
import { buildSvgDiagram, downloadPng, downloadSvg } from '@/lib/erd/svgExport';
import { validateCanvas, type ErdIssue } from '@/lib/erd/validation';
import { zoneQueries } from '@/lib/queries/zones';
import type {
	ErdCanvas as ErdCanvasModel,
	ErdAssistantAction,
	ErdCardinality,
	ErdExportFormat,
	ErdNode,
	ErdNote,
	ErdArea,
	ErdVersion,
	ErdViewport,
	SqlDialect,
} from '@/types/erd';
import type { Zone } from '@/types/zones';
import { AddTableDialog, type DraftTable } from './AddTableDialog';
import { ConfirmDialog, type ConfirmRequest } from './ConfirmDialog';
import { ErdCanvas, type ColumnConnection, type ErdCanvasHandle } from './ErdCanvas';
import { ErdAssistant } from './ErdAssistant';
import { ErdToolbar } from './ErdToolbar';
import { ImportExportDialog } from './ImportExportDialog';
import { RelationshipPanel } from './RelationshipPanel';
import { TableEditorDialog } from './TableEditorDialog';
import { ValidationPanel } from './ValidationPanel';
import { VersionsDialog } from './VersionsDialog';
import { TemplatesDialog } from './TemplatesDialog';
import type { TableTemplate } from '@/lib/erd/templates';

const DEFAULT_VIEWPORT: ErdViewport = { x: 0, y: 0, zoom: 1 };
const LAST_ZONE_KEY = 'erd:last-zone';

export const ErdView = () => {
	const router = useRouter();
	const { data: session } = useSession();
	const [zones, setZones] = useState<Zone[]>([]);
	const [zoneId, setZoneId] = useState<string | null>(null);
	const [canvas, setCanvas] = useState<ErdCanvasModel | null>(null);
	const [nodes, setNodes] = useState<ErdNode[]>([]);
	const [notes, setNotes] = useState<ErdNote[]>([]);
	const [areas, setAreas] = useState<ErdArea[]>([]);
	const [viewport, setViewport] = useState<ErdViewport>(DEFAULT_VIEWPORT);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);
	const [search, setSearch] = useState('');
	const [selectedRelationshipId, setSelectedRelationshipId] = useState<string | null>(null);
	const [selectedNodeIds, setSelectedNodeIds] = useState<ReadonlySet<string>>(new Set());
	const [transferOpen, setTransferOpen] = useState(false);
	const [addOpen, setAddOpen] = useState(false);
	const [editingNodeId, setEditingNodeId] = useState<string | null>(null);
	const [issuesOpen, setIssuesOpen] = useState(false);
	const [hiddenOpen, setHiddenOpen] = useState(false);
	const [snapToGrid, setSnapToGrid] = useState(true);
	const [showMinimap, setShowMinimap] = useState(true);
	const [clipboardCount, setClipboardCount] = useState(0);
	const [versionsOpen, setVersionsOpen] = useState(false);
	const [versions, setVersions] = useState<ErdVersion[]>([]);
	const [versionsBusy, setVersionsBusy] = useState(false);
	const [templatesOpen, setTemplatesOpen] = useState(false);
	const [templatesBusy, setTemplatesBusy] = useState(false);
	const [fitRequest, setFitRequest] = useState(0);
	const [confirmRequest, setConfirmRequest] = useState<ConfirmRequest | null>(null);
	const [savingTable, setSavingTable] = useState(false);
	const [busy, setBusy] = useState(false);
	const [warnings, setWarnings] = useState<string[]>([]);
	const [historyCounts, setHistoryCounts] = useState({ undo: 0, redo: 0 });

	const canvasRef = useRef<ErdCanvasHandle>(null);
	const nodesRef = useRef<ErdNode[]>([]);
	const notesRef = useRef<ErdNote[]>([]);
	const areasRef = useRef<ErdArea[]>([]);
	const areaNameTimer = useRef<number | null>(null);
	const viewportTimer = useRef<number | null>(null);
	const columnReorderSeq = useRef(new Map<string, number>());
	const columnWriteQueue = useRef(new Map<string, Promise<unknown>>());
	const canvasRefMirror = useRef<ErdCanvasModel | null>(null);
	// Undo/redo state lives in its own object so the stack rules are not
	// repeated in every handler that mutates the canvas.
	const history = useMemo(() => new CanvasHistory(), []);
	const undoInFlight = useRef(false);

	useEffect(() => {
		nodesRef.current = nodes;
	}, [nodes]);

	useEffect(() => {
		notesRef.current = notes;
	}, [notes]);

	useEffect(() => {
		areasRef.current = areas;
	}, [areas]);

	useEffect(() => {
		if (fitRequest === 0) return undefined;
		const id = window.setTimeout(() => canvasRef.current?.fit(), 0);
		return () => window.clearTimeout(id);
	}, [fitRequest]);

	useEffect(() => {
		// Deferred so the first paint matches the server (localStorage is not
		// readable there) and the effect does not cascade a second render.
		const id = window.setTimeout(
			() => setClipboardCount(readClipboard()?.nodes.length ?? 0),
			0,
		);
		return () => window.clearTimeout(id);
	}, []);

	useEffect(() => {
		canvasRefMirror.current = canvas;
	}, [canvas]);

	const role = (session?.user as { role?: string } | undefined)?.role;
	const readOnly = role !== 'admin';
	const userId = session?.user.id ?? '';
	// The root layout already read this list for the session and handed it to
	// the query cache; subscribing here reuses that read instead of asking
	// `/api/zones` again before the canvas can start loading.
	const zonesQuery = useQuery({
		...zoneQueries.list(userId),
		enabled: userId !== '',
	});

	// Reopening the page can start on the zone that was open last time, so the
	// canvas read does not have to wait for the zone list before it begins.
	useEffect(() => {
		const stored = window.localStorage.getItem(LAST_ZONE_KEY);
		if (stored) setZoneId((current) => current ?? stored);
	}, []);

	useEffect(() => {
		if (zoneId) window.localStorage.setItem(LAST_ZONE_KEY, zoneId);
	}, [zoneId]);

	const syncHistoryCounts = useCallback(() => {
		setHistoryCounts(history.counts);
	}, [history]);

	/** The canvas as it stands right now, cloned — what undo/redo stores. */
	const snapshotNow = useCallback((): CanvasSnapshot | null => {
		const current = canvasRefMirror.current;
		if (!current) return null;
		return {
			nodes: structuredClone(nodesRef.current),
			relationships: structuredClone(current.relationships),
			notes: structuredClone(notesRef.current),
			areas: structuredClone(areasRef.current),
		};
	}, []);

	/** Remember the canvas as it stands, before the next mutation changes it. */
	const pushHistory = useCallback(() => {
		const snapshot = snapshotNow();
		if (!snapshot) return;
		history.remember(snapshot);
		syncHistoryCounts();
	}, [history, snapshotNow, syncHistoryCounts]);

	const applySnapshot = useCallback((snapshot: CanvasSnapshot) => {
		setNodes(structuredClone(snapshot.nodes));
		setNotes(structuredClone(snapshot.notes));
		setAreas(structuredClone(snapshot.areas));
		setCanvas((current) =>
			current
				? { ...current, relationships: structuredClone(snapshot.relationships) }
				: current,
		);
		setSelectedRelationshipId(null);
		setSelectedNodeIds(new Set());
	}, []);

	const persistSnapshot = useCallback(
		(snapshot: CanvasSnapshot) => {
			if (!zoneId) return;
			undoInFlight.current = true;
			void erdApi.restoreState(zoneId, snapshot).then((response) => {
				undoInFlight.current = false;
				if (response.error) {
					setError(response.message ?? t('Failed to save the change'));
				} else if (response.data) {
					// The server's answer is authoritative for hidden tombstones,
					// which the snapshot itself does not carry.
					setCanvas(response.data);
				}
			});
		},
		[zoneId],
	);

	const undo = useCallback(() => {
		if (readOnly || undoInFlight.current || history.counts.undo === 0) return;
		const current = snapshotNow();
		if (!current) return;
		const previous = history.takeUndo(current);
		if (!previous) return;
		applySnapshot(previous);
		persistSnapshot(previous);
		syncHistoryCounts();
	}, [applySnapshot, history, persistSnapshot, readOnly, snapshotNow, syncHistoryCounts]);

	const redo = useCallback(() => {
		if (readOnly || undoInFlight.current || history.counts.redo === 0) return;
		const current = snapshotNow();
		if (!current) return;
		const next = history.takeRedo(current);
		if (!next) return;
		applySnapshot(next);
		persistSnapshot(next);
		syncHistoryCounts();
	}, [applySnapshot, history, persistSnapshot, readOnly, snapshotNow, syncHistoryCounts]);

	useEffect(() => {
		if (zonesQuery.data) setZones(zonesQuery.data);
	}, [zonesQuery.data]);

	useEffect(() => {
		if (!zonesQuery.error) return;
		setError(zonesQuery.error.message || t('Failed to load zones'));
		setLoading(false);
	}, [zonesQuery.error]);

	useEffect(() => {
		if (!userId || !zonesQuery.data) return;
		const requested = new URLSearchParams(window.location.search).get('zone');
		const fallback =
			zonesQuery.data.find((zone) => zone.id === requested) ?? zonesQuery.data[0] ?? null;
		// Keep the zone already open (including the remembered one) when the
		// loaded list still contains it; only fall back when it does not.
		if (zoneId && zonesQuery.data.some((zone) => zone.id === zoneId)) return;
		if (zoneId) setError(null);
		setZoneId(fallback?.id ?? null);
		if (!fallback) setLoading(false);
	}, [userId, zonesQuery.data, zoneId]);

	useEffect(() => {
		if (!zoneId) return undefined;
		let cancelled = false;
		erdApi.getCanvas(zoneId).then((response) => {
			if (cancelled) return;
			if (response.error || !response.data) {
				setError(response.message ?? t('Failed to load the canvas'));
				setCanvas(null);
				setNodes([]);
				setLoading(false);
				return;
			}
			const next = response.data;
			setCanvas(next);
			setNodes(next.nodes);
			setNotes(next.notes);
			setAreas(next.areas);
			setViewport(next.viewport);
			setSelectedRelationshipId(null);
			setWarnings([]);
			setLoading(false);
			const isDefaultView =
				next.viewport.x === 0 && next.viewport.y === 0 && next.viewport.zoom === 1;
			if (next.nodes.length > 0 && isDefaultView) {
				setFitRequest((value) => value + 1);
			}
		});
		return () => {
			cancelled = true;
		};
	}, [zoneId]);

	const handleZoneChange = useCallback((nextZoneId: string) => {
		setError(null);
		setSelectedRelationshipId(null);
		setSelectedNodeIds(new Set());
		setNotes([]);
		setAreas([]);
		setWarnings([]);
		setZoneId(nextZoneId);
	}, []);

	const persistViewport = useCallback(
		(next: ErdViewport) => {
			if (!zoneId) return;
			if (viewportTimer.current) window.clearTimeout(viewportTimer.current);
			viewportTimer.current = window.setTimeout(() => {
				void erdApi.updateViewport(zoneId, next);
			}, 600);
		},
		[zoneId],
	);

	const handleViewportChange = useCallback(
		(next: ErdViewport) => {
			setViewport(next);
			persistViewport(next);
		},
		[persistViewport],
	);

	const handleNodeSelect = useCallback((nodeId: string, additive: boolean) => {
		setSelectedRelationshipId(null);
		setSelectedNodeIds((current) => {
			if (!additive) return new Set([nodeId]);
			const next = new Set(current);
			if (next.has(nodeId)) next.delete(nodeId);
			else next.add(nodeId);
			return next;
		});
	}, []);

	const handleClearSelection = useCallback(() => {
		setSelectedNodeIds((current) => (current.size === 0 ? current : new Set()));
	}, []);

	const handleNodesMove = useCallback((updates: { id: string; x: number; y: number }[]) => {
		setNodes((current) =>
			current.map((node) => {
				const update = updates.find((row) => row.id === node.id);
				return update ? { ...node, x: update.x, y: update.y } : node;
			}),
		);
	}, []);

	const handleNodesMoveEnd = useCallback((nodeIds: string[]) => {
		nodeIds.forEach((nodeId) => {
			const node = nodesRef.current.find((row) => row.id === nodeId);
			if (!node) return;
			void erdApi.updateNode(nodeId, { x: node.x, y: node.y }).then((response) => {
				if (response.error) {
					setError(response.message ?? t('Failed to save the position'));
				}
			});
		});
	}, []);

	const handleNodeResize = useCallback((nodeId: string, width: number) => {
		const nextNodes = nodesRef.current.map((node) =>
			node.id === nodeId ? { ...node, width } : node,
		);
		nodesRef.current = nextNodes;
		setNodes(nextNodes);
	}, []);

	const handleNodeResizeEnd = useCallback((nodeId: string) => {
		const node = nodesRef.current.find((row) => row.id === nodeId);
		if (!node || node.width == null) return;
		void erdApi.updateNode(nodeId, { width: node.width }).then((response) => {
			if (response.error) setError(response.message ?? t('Failed to save the table'));
		});
	}, []);

	const handleReorderColumns = useCallback(
		(nodeId: string, fromIndex: number, toIndex: number) => {
			if (readOnly) return;
			if (fromIndex === toIndex) return;
			const node = nodesRef.current.find((row) => row.id === nodeId);
			if (!node) return;
			const columns = moveItem(node.columns, fromIndex, toIndex);

			pushHistory();
			const order = columns.map((column) => column.name);
			const nextNodes = nodesRef.current.map((row) =>
				row.id === nodeId ? { ...row, columns, column_order: order } : row,
			);
			// Keep the ref in step immediately: a second drag can land before
			// React has committed the optimistic update.
			nodesRef.current = nextNodes;
			setNodes(nextNodes);

			const sequence = (columnReorderSeq.current.get(nodeId) ?? 0) + 1;
			columnReorderSeq.current.set(nodeId, sequence);
			// Serialise writes per card. Two drags in quick succession must not
			// race and leave the server holding the earlier order.
			const previous = columnWriteQueue.current.get(nodeId) ?? Promise.resolve();
			const write = previous.then(() => erdApi.updateNode(nodeId, { column_order: order }));
			columnWriteQueue.current.set(nodeId, write);
			void write.then((response) => {
				if (columnReorderSeq.current.get(nodeId) !== sequence) return;
				if (response.error || !response.data) {
					setError(response.message ?? t('Failed to save the table'));
					return;
				}
				const updated = response.data;
				setNodes((current) =>
					current.map((row) => {
						if (row.id !== nodeId) return row;
						return {
							...row,
							columns: updated.columns,
							column_order: updated.column_order ?? order,
						};
					}),
				);
			});
		},
		[pushHistory, readOnly],
	);

	const handleToggleCollapse = useCallback(
		(nodeId: string) => {
			const node = nodesRef.current.find((row) => row.id === nodeId);
			if (!node) return;
			pushHistory();
			const collapsed = !node.collapsed;
			setNodes((current) =>
				current.map((row) => (row.id === nodeId ? { ...row, collapsed } : row)),
			);
			void erdApi.updateNode(nodeId, { collapsed }).then((response) => {
				if (response.error) setError(response.message ?? t('Failed to save the table'));
			});
		},
		[pushHistory],
	);

	/** Remove tables after confirmation: optimistic locally, then server-side. */
	const removeNodesNow = useCallback(
		(ids: string[]) => {
			pushHistory();
			const removed = new Set(ids);
			const hiddenNow = nodesRef.current
				.filter((node) => removed.has(node.id) && node.table_id != null)
				.map((node) => ({
					id: node.id,
					table_id: node.table_id,
					name: node.name,
				}));
			setNodes((current) => current.filter((row) => !removed.has(row.id)));
			setCanvas((current) =>
				current
					? {
							...current,
							relationships: current.relationships.filter(
								(rel) =>
									!removed.has(rel.source_node_id) &&
									!removed.has(rel.target_node_id),
							),
							hidden_nodes: [...current.hidden_nodes, ...hiddenNow],
						}
					: current,
			);
			setSelectedNodeIds((current) => {
				const next = new Set(current);
				ids.forEach((id) => next.delete(id));
				return next;
			});
			setSelectedRelationshipId(null);
			ids.forEach((id) => {
				void erdApi.deleteNode(id).then((response) => {
					if (response.error) {
						setError(response.message ?? t('Failed to remove the table'));
					}
				});
			});
		},
		[pushHistory],
	);

	const handleDeleteNode = useCallback(
		(nodeId: string) => {
			if (readOnly) return;
			const node = nodesRef.current.find((row) => row.id === nodeId);
			if (!node) return;
			setConfirmRequest({
				title: t('Remove table'),
				message: t('Remove {0} from this canvas?', { 0: node.name }),
				confirmLabel: t('Remove'),
				onConfirm: () => removeNodesNow([nodeId]),
			});
		},
		[readOnly, removeNodesNow],
	);

	const handleDeleteSelected = useCallback(() => {
		if (readOnly) return;
		const ids = [...selectedNodeIds];
		if (ids.length === 0) return;
		setConfirmRequest({
			title: t('Remove tables'),
			message: t('Remove {0} table(s) from this canvas?', { 0: String(ids.length) }),
			confirmLabel: t('Remove'),
			onConfirm: () => removeNodesNow(ids),
		});
	}, [readOnly, removeNodesNow, selectedNodeIds]);

	/** Copy the selection. Catalog tables are copied as canvas-only tables. */
	const handleDuplicateSelected = useCallback(() => {
		if (!canvas || readOnly) return;
		const originals = nodes.filter((node) => selectedNodeIds.has(node.id));
		if (originals.length === 0) return;
		pushHistory();
		void Promise.all(
			originals.map(async (node) => {
				const response = await erdApi.createNode({
					canvas_id: canvas.id,
					name: `${node.name} (copy)`,
					columns: node.columns,
					indexes: node.indexes,
					note: node.note,
					x: node.x + 40,
					y: node.y + 40,
					width: node.width,
				});
				if (response.error || !response.data) {
					setError(response.message ?? t('Failed to duplicate the table'));
					return null;
				}
				return { original: node.id, copy: response.data };
			}),
		).then((results) => {
			const created = results.filter(
				(row): row is { original: string; copy: ErdNode } => row !== null,
			);
			if (created.length === 0) return;
			setNodes((current) => [...current, ...created.map((row) => row.copy)]);
			setSelectedNodeIds(new Set(created.map((row) => row.copy.id)));
			const byOriginal = new Map(created.map((row) => [row.original, row.copy.id]));
			canvas.relationships.forEach((rel) => {
				const sourceId = byOriginal.get(rel.source_node_id);
				const targetId = byOriginal.get(rel.target_node_id);
				if (!sourceId || !targetId) return;
				void erdApi
					.createRelationship({
						canvas_id: canvas.id,
						source_node_id: sourceId,
						target_node_id: targetId,
						source_columns: rel.source_columns,
						target_columns: rel.target_columns,
						cardinality: rel.cardinality,
						label: rel.label,
					})
					.then((response) => {
						if (response.data) {
							const createdRel = response.data;
							setCanvas((current) =>
								current
									? {
											...current,
											relationships: [...current.relationships, createdRel],
										}
									: current,
							);
						}
					});
			});
		});
	}, [canvas, nodes, pushHistory, readOnly, selectedNodeIds]);

	const handleRestoreNode = useCallback((nodeId: string) => {
		void erdApi.restoreNode(nodeId).then((response) => {
			if (response.error || !response.data) {
				setError(response.message ?? t('Failed to restore the table'));
				return;
			}
			const node = response.data;
			setNodes((current) => [...current, node]);
			setCanvas((current) =>
				current
					? {
							...current,
							hidden_nodes: current.hidden_nodes.filter((row) => row.id !== nodeId),
						}
					: current,
			);
		});
	}, []);

	/** Lift the selection onto the clipboard, relationships included. */
	const handleCopySelected = useCallback(() => {
		const chosen = nodesRef.current.filter((node) => selectedNodeIds.has(node.id));
		if (chosen.length === 0) return;
		const names = new Set(chosen.map((node) => node.name));
		const nameById = new Map(nodesRef.current.map((node) => [node.id, node.name]));
		const relationships = (canvasRefMirror.current?.relationships ?? [])
			.filter(
				(rel) =>
					names.has(nameById.get(rel.source_node_id) ?? '') &&
					names.has(nameById.get(rel.target_node_id) ?? ''),
			)
			.map((rel) => ({
				source: nameById.get(rel.source_node_id) as string,
				target: nameById.get(rel.target_node_id) as string,
				source_columns: rel.source_columns,
				target_columns: rel.target_columns,
				cardinality: rel.cardinality,
				label: rel.label,
			}));
		const payload: ErdClipboard = {
			nodes: chosen.map((node) => ({
				name: node.name,
				columns: node.columns,
				indexes: node.indexes,
				note: node.note,
				x: node.x,
				y: node.y,
				width: node.width,
			})),
			relationships,
			offset: 40,
		};
		writeClipboard(payload);
		setClipboardCount(chosen.length);
	}, [selectedNodeIds]);

	/** Paste as canvas-only copies, so this works across zones too. */
	const handlePaste = useCallback(async () => {
		if (!canvas || readOnly) return;
		const clip = readClipboard();
		if (!clip || clip.nodes.length === 0) return;
		pushHistory();
		const taken = new Set(nodesRef.current.map((node) => node.name));
		const idByName = new Map<string, string>();
		const created: ErdNode[] = [];

		for (const node of clip.nodes) {
			let name = node.name;
			let attempt = 1;
			while (taken.has(name)) {
				name = `${node.name} (copy${attempt > 1 ? ` ${attempt}` : ''})`;
				attempt += 1;
			}
			taken.add(name);
			const response = await erdApi.createNode({
				canvas_id: canvas.id,
				name,
				columns: node.columns,
				indexes: node.indexes,
				note: node.note,
				x: node.x + clip.offset,
				y: node.y + clip.offset,
				width: node.width,
			});
			if (response.error || !response.data) {
				setError(response.message ?? t('Failed to paste the table'));
				continue;
			}
			idByName.set(node.name, response.data.id);
			created.push(response.data);
		}

		if (created.length > 0) {
			setNodes((current) => [...current, ...created]);
			setSelectedNodeIds(new Set(created.map((node) => node.id)));
		}

		for (const rel of clip.relationships) {
			const sourceId = idByName.get(rel.source);
			const targetId = idByName.get(rel.target);
			if (!sourceId || !targetId) continue;
			const response = await erdApi.createRelationship({
				canvas_id: canvas.id,
				source_node_id: sourceId,
				target_node_id: targetId,
				source_columns: rel.source_columns,
				target_columns: rel.target_columns,
				cardinality: rel.cardinality,
				label: rel.label,
			});
			if (response.data) {
				const createdRel = response.data;
				setCanvas((current) =>
					current
						? { ...current, relationships: [...current.relationships, createdRel] }
						: current,
				);
			}
		}

		writeClipboard({ ...clip, offset: clip.offset + 40 });
	}, [canvas, pushHistory, readOnly]);

	const handleAddNote = useCallback(() => {
		if (!canvas || readOnly) return;
		pushHistory();
		const offset = notesRef.current.length * 24;
		void erdApi
			.createNote({
				canvas_id: canvas.id,
				text: '',
				x: 80 + offset,
				y: 80 + offset,
			})
			.then((response) => {
				if (response.error || !response.data) {
					setError(response.message ?? t('Failed to add the note'));
					return;
				}
				setNotes((current) => [...current, response.data]);
			});
	}, [canvas, pushHistory, readOnly]);

	const handleNoteMove = useCallback((noteId: string, x: number, y: number) => {
		const nextNotes = notesRef.current.map((note) =>
			note.id === noteId ? { ...note, x, y } : note,
		);
		notesRef.current = nextNotes;
		setNotes(nextNotes);
	}, []);

	const handleNoteMoveEnd = useCallback((noteId: string) => {
		const note = notesRef.current.find((row) => row.id === noteId);
		if (!note) return;
		void erdApi.updateNote(noteId, { x: note.x, y: note.y }).then((response) => {
			if (response.error) setError(response.message ?? t('Failed to save the note'));
		});
	}, []);

	const handleNoteResize = useCallback((noteId: string, width: number, height: number) => {
		const nextNotes = notesRef.current.map((note) =>
			note.id === noteId ? { ...note, width, height } : note,
		);
		notesRef.current = nextNotes;
		setNotes(nextNotes);
	}, []);

	const handleNoteResizeEnd = useCallback((noteId: string) => {
		const note = notesRef.current.find((row) => row.id === noteId);
		if (!note) return;
		void erdApi
			.updateNote(noteId, { width: note.width, height: note.height })
			.then((response) => {
				if (response.error) {
					setError(response.message ?? t('Failed to save the note'));
				}
			});
	}, []);

	const handleNoteTextChange = useCallback((noteId: string, text: string) => {
		setNotes((current) =>
			current.map((note) => (note.id === noteId ? { ...note, text } : note)),
		);
	}, []);

	const handleNoteTextCommit = useCallback((noteId: string) => {
		const note = notesRef.current.find((row) => row.id === noteId);
		if (!note) return;
		void erdApi.updateNote(noteId, { text: note.text }).then((response) => {
			if (response.error) setError(response.message ?? t('Failed to save the note'));
		});
	}, []);

	const handleNoteDelete = useCallback(
		(noteId: string) => {
			if (readOnly) return;
			pushHistory();
			void erdApi.deleteNote(noteId).then((response) => {
				if (response.error) {
					setError(response.message ?? t('Failed to delete the note'));
					return;
				}
				setNotes((current) => current.filter((note) => note.id !== noteId));
				setCanvas((current) =>
					current
						? { ...current, notes: current.notes.filter((note) => note.id !== noteId) }
						: current,
				);
			});
		},
		[pushHistory, readOnly],
	);

	const handleAddArea = useCallback(() => {
		if (!canvas || readOnly) return;
		pushHistory();
		// Put a new region below whatever is already drawn. Areas render behind
		// the cards, so dropping one on top of the diagram would hide its header.
		const bottom = nodesRef.current.reduce((value, node) => Math.max(value, node.y), 0);
		void erdApi
			.createArea({ canvas_id: canvas.id, name: '', x: 40, y: bottom + 420 })
			.then((response) => {
				if (response.error || !response.data) {
					setError(response.message ?? t('Failed to add the area'));
					return;
				}
				setAreas((current) => [...current, response.data]);
				// The new region sits below the existing diagram; bring it into
				// view instead of leaving the user staring at the old framing.
				setFitRequest((value) => value + 1);
			});
	}, [canvas, pushHistory, readOnly]);

	const handleAreaMove = useCallback((areaId: string, x: number, y: number) => {
		setAreas((current) =>
			current.map((area) => (area.id === areaId ? { ...area, x, y } : area)),
		);
	}, []);

	const handleAreaMoveEnd = useCallback((areaId: string) => {
		const area = areasRef.current.find((row) => row.id === areaId);
		if (!area) return;
		void erdApi.updateArea(areaId, { x: area.x, y: area.y }).then((response) => {
			if (response.error) setError(response.message ?? t('Failed to save the area'));
		});
	}, []);

	const handleAreaResize = useCallback((areaId: string, width: number, height: number) => {
		setAreas((current) =>
			current.map((area) => (area.id === areaId ? { ...area, width, height } : area)),
		);
	}, []);

	const handleAreaResizeEnd = useCallback((areaId: string) => {
		const area = areasRef.current.find((row) => row.id === areaId);
		if (!area) return;
		void erdApi
			.updateArea(areaId, { width: area.width, height: area.height })
			.then((response) => {
				if (response.error) {
					setError(response.message ?? t('Failed to save the area'));
				}
			});
	}, []);

	const handleAreaRename = useCallback((areaId: string, name: string) => {
		setAreas((current) =>
			current.map((area) => (area.id === areaId ? { ...area, name } : area)),
		);
		if (areaNameTimer.current) window.clearTimeout(areaNameTimer.current);
		areaNameTimer.current = window.setTimeout(() => {
			void erdApi.updateArea(areaId, { name }).then((response) => {
				if (response.error) {
					setError(response.message ?? t('Failed to save the area'));
				}
			});
		}, 400);
	}, []);

	const handleAreaDelete = useCallback(
		(areaId: string) => {
			if (readOnly) return;
			pushHistory();
			void erdApi.deleteArea(areaId).then((response) => {
				if (response.error) {
					setError(response.message ?? t('Failed to delete the area'));
					return;
				}
				setAreas((current) => current.filter((area) => area.id !== areaId));
				setCanvas((current) =>
					current
						? { ...current, areas: current.areas.filter((area) => area.id !== areaId) }
						: current,
				);
			});
		},
		[pushHistory, readOnly],
	);

	const openVersions = useCallback(() => {
		if (!zoneId) return;
		setVersionsOpen(true);
		void erdApi.listVersions(zoneId).then((response) => {
			if (response.error || !response.data) {
				setError(response.message ?? t('Failed to load versions'));
				return;
			}
			setVersions(response.data);
		});
	}, [zoneId]);

	const handleCreateVersion = useCallback(
		(label: string) => {
			if (!zoneId) return;
			setVersionsBusy(true);
			void erdApi.createVersion(zoneId, label, session?.user.id).then((response) => {
				setVersionsBusy(false);
				if (response.error || !response.data) {
					setError(response.message ?? t('Failed to save the version'));
					return;
				}
				setVersions((current) => [response.data, ...current]);
			});
		},
		[session?.user.id, zoneId],
	);

	const handleRestoreVersion = useCallback(
		(version: ErdVersion) => {
			setConfirmRequest({
				title: t('Restore version'),
				message: t('Replace the current canvas with this version? You can undo it.'),
				confirmLabel: t('Restore'),
				onConfirm: () => {
					pushHistory();
					void erdApi.restoreVersion(version.id).then((response) => {
						if (response.error || !response.data) {
							setError(response.message ?? t('Failed to restore the version'));
							return;
						}
						const canvasData = response.data;
						setCanvas(canvasData);
						setNodes(canvasData.nodes);
						setNotes(canvasData.notes);
						setAreas(canvasData.areas);
						setSelectedNodeIds(new Set());
						setSelectedRelationshipId(null);
						setVersionsOpen(false);
					});
				},
			});
		},
		[pushHistory],
	);

	const handleDeleteVersion = useCallback((version: ErdVersion) => {
		void erdApi.deleteVersion(version.id).then((response) => {
			if (response.error) {
				setError(response.message ?? t('Failed to delete the version'));
				return;
			}
			setVersions((current) => current.filter((row) => row.id !== version.id));
		});
	}, []);

	/** Insert a template's tables and the relationships between them. */
	const handleInsertTemplate = useCallback(
		async (template: TableTemplate) => {
			if (!canvas || readOnly) return;
			pushHistory();
			setTemplatesBusy(true);
			const taken = new Set(nodesRef.current.map((node) => node.name));
			const baseY =
				nodesRef.current.reduce((value, node) => Math.max(value, node.y), 0) + 220;
			const idByName = new Map<string, string>();
			const created: ErdNode[] = [];

			for (const [index, table] of template.tables.entries()) {
				let name = table.name;
				let attempt = 1;
				while (taken.has(name)) {
					name = `${table.name} (${attempt})`;
					attempt += 1;
				}
				taken.add(name);
				const response = await erdApi.createNode({
					canvas_id: canvas.id,
					name,
					columns: table.columns,
					indexes: table.indexes ?? null,
					note: table.note ?? null,
					x: 40 + index * 320,
					y: baseY,
				});
				if (response.error || !response.data) {
					setError(response.message ?? t('Failed to insert the template'));
					continue;
				}
				idByName.set(table.name, response.data.id);
				created.push(response.data);
			}

			if (created.length > 0) {
				setNodes((current) => [...current, ...created]);
				setSelectedNodeIds(new Set(created.map((node) => node.id)));
			}
			for (const rel of template.relationships) {
				const sourceId = idByName.get(rel.source);
				const targetId = idByName.get(rel.target);
				if (!sourceId || !targetId) continue;
				const response = await erdApi.createRelationship({
					canvas_id: canvas.id,
					source_node_id: sourceId,
					target_node_id: targetId,
					source_columns: rel.source_columns,
					target_columns: rel.target_columns,
					cardinality: rel.cardinality,
					label: null,
				});
				if (response.data) {
					const createdRel = response.data;
					setCanvas((current) =>
						current
							? { ...current, relationships: [...current.relationships, createdRel] }
							: current,
					);
				}
			}
			setTemplatesBusy(false);
			setTemplatesOpen(false);
			setFitRequest((value) => value + 1);
		},
		[canvas, pushHistory, readOnly],
	);

	const handleConnect = useCallback(
		(source: ColumnConnection, target: ColumnConnection) => {
			if (!canvas || readOnly || !target.column) return;
			pushHistory();
			void erdApi
				.createRelationship({
					canvas_id: canvas.id,
					source_node_id: source.nodeId,
					target_node_id: target.nodeId,
					source_columns: source.column ? [source.column] : [],
					target_columns: [target.column],
					cardinality: 'one-to-one',
				})
				.then((response) => {
					if (response.error || !response.data) {
						setError(response.message ?? t('Failed to create the relationship'));
						return;
					}
					const relationship = response.data;
					setCanvas((current) =>
						current
							? {
									...current,
									relationships: [...current.relationships, relationship],
								}
							: current,
					);
					setSelectedRelationshipId(relationship.id);
				});
		},
		[canvas, pushHistory, readOnly],
	);

	const handleRelationshipChange = useCallback(
		(patch: { cardinality?: ErdCardinality; label?: string }) => {
			if (!selectedRelationshipId) return;
			pushHistory();
			void erdApi.updateRelationship(selectedRelationshipId, patch).then((response) => {
				if (response.error || !response.data) {
					setError(response.message ?? t('Failed to save the relationship'));
					return;
				}
				const updated = response.data;
				setCanvas((current) =>
					current
						? {
								...current,
								relationships: current.relationships.map((rel) =>
									rel.id === updated.id ? updated : rel,
								),
							}
						: current,
				);
			});
		},
		[pushHistory, selectedRelationshipId],
	);

	const deleteRelationshipById = useCallback(
		(relId: string) => {
			pushHistory();
			void erdApi.deleteRelationship(relId).then((response) => {
				if (response.error) {
					setError(response.message ?? t('Failed to delete the relationship'));
					return;
				}
				setCanvas((current) =>
					current
						? {
								...current,
								relationships: current.relationships.filter(
									(rel) => rel.id !== relId,
								),
							}
						: current,
				);
				setSelectedRelationshipId((current) => (current === relId ? null : current));
			});
		},
		[pushHistory],
	);

	const handleDeleteRelationship = useCallback(() => {
		if (!selectedRelationshipId) return;
		deleteRelationshipById(selectedRelationshipId);
	}, [deleteRelationshipById, selectedRelationshipId]);

	const handleAutoArrange = useCallback(() => {
		if (!canvas) return;
		pushHistory();
		const placement =
			canvas.relationships.length === 0
				? gridLayout(nodes)
				: layeredLayout(nodes, canvas.relationships);
		setNodes((current) =>
			current.map((node) => ({
				...node,
				x: placement[node.id]?.x ?? node.x,
				y: placement[node.id]?.y ?? node.y,
			})),
		);
		setFitRequest((value) => value + 1);
		nodes.forEach((node) => {
			const next = placement[node.id];
			if (!next) return;
			void erdApi.updateNode(node.id, next);
		});
	}, [canvas, nodes, pushHistory]);

	const handleAddTable = useCallback(
		(table: DraftTable) => {
			if (!canvas) return;
			pushHistory();
			const maxY = nodes.reduce((value, node) => Math.max(value, node.y), 0);
			void erdApi
				.createNode({
					canvas_id: canvas.id,
					name: table.name,
					columns: table.columns.map((column) => ({
						name: column.name,
						data_type: column.data_type,
						is_primary_key: column.is_primary_key,
					})),
					x: 40,
					y: maxY + 300,
				})
				.then((response) => {
					if (response.error || !response.data) {
						setError(response.message ?? t('Failed to add the table'));
						return;
					}
					setNodes((current) => [...current, response.data]);
				});
		},
		[canvas, nodes, pushHistory],
	);

	const handleImport = useCallback(
		(format: ErdExportFormat, content: string, replace: boolean) => {
			if (!zoneId) return;
			setBusy(true);
			pushHistory();
			void erdApi.importCanvas(zoneId, { format, content, replace }).then((response) => {
				setBusy(false);
				if (response.error || !response.data) {
					setError(response.message ?? t('Failed to import the document'));
					return;
				}
				const result = response.data;
				setCanvas(result.canvas);
				setNodes(result.canvas.nodes);
				setNotes(result.canvas.notes);
				setAreas(result.canvas.areas);
				setViewport(result.canvas.viewport);
				setSelectedNodeIds(new Set());
				setWarnings(result.warnings);
				setFitRequest((value) => value + 1);
			});
		},
		[pushHistory, zoneId],
	);

	const handleExport = useCallback(
		(format: ErdExportFormat, dialect: SqlDialect = 'postgres') => {
			if (!zoneId) return;
			setBusy(true);
			void erdApi.exportCanvas(zoneId, format, dialect).then((response) => {
				setBusy(false);
				if (response.error || !response.data) {
					setError(response.message ?? t('Failed to export the canvas'));
					return;
				}
				const file = response.data;
				downloadText(
					file.filename,
					file.content,
					format === 'json' ? 'application/json' : 'text/plain',
				);
			});
		},
		[zoneId],
	);

	const handleExportImage = useCallback(
		(kind: 'svg' | 'png') => {
			if (!canvas) return;
			const diagram = buildSvgDiagram(nodes, canvas.relationships, notes);
			if (!diagram) {
				setError(t('There is nothing to export yet'));
				return;
			}
			const name = (canvas.zone_name ?? 'canvas').replace(/[^\w.-]+/g, '-');
			if (kind === 'svg') {
				downloadSvg(diagram, `${name}.svg`);
				return;
			}
			void downloadPng(diagram, `${name}.png`).catch(() => {
				setError(t('Failed to export the image'));
			});
		},
		[canvas, nodes, notes],
	);

	useEffect(() => {
		const onKeyDown = (event: KeyboardEvent) => {
			const modifier = event.ctrlKey || event.metaKey;
			if (modifier && event.key.toLowerCase() === 'z') {
				event.preventDefault();
				if (event.shiftKey) redo();
				else undo();
				return;
			}
			if (modifier && event.key.toLowerCase() === 'y') {
				event.preventDefault();
				redo();
				return;
			}
			if (modifier && event.key.toLowerCase() === 'd') {
				event.preventDefault();
				handleDuplicateSelected();
				return;
			}
			if (modifier && event.key.toLowerCase() === 'c') {
				event.preventDefault();
				handleCopySelected();
				return;
			}
			if (modifier && event.key.toLowerCase() === 'v') {
				event.preventDefault();
				void handlePaste();
				return;
			}
			if (event.key !== 'Delete' && event.key !== 'Backspace') return;
			const tag = (event.target as HTMLElement | null)?.tagName;
			if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
			if (selectedNodeIds.size > 0) {
				event.preventDefault();
				handleDeleteSelected();
				return;
			}
			if (!selectedRelationshipId || readOnly) return;
			event.preventDefault();
			handleDeleteRelationship();
		};
		window.addEventListener('keydown', onKeyDown);
		return () => window.removeEventListener('keydown', onKeyDown);
	}, [
		handleDeleteRelationship,
		handleDeleteSelected,
		handleDuplicateSelected,
		handleCopySelected,
		handlePaste,
		readOnly,
		redo,
		selectedNodeIds,
		selectedRelationshipId,
		undo,
	]);

	const editingNode = nodes.find((node) => node.id === editingNodeId) ?? null;

	const handleSaveTable = useCallback(
		(patch: {
			name: string;
			note: string | null;
			indexes: { name: string | null; columns: string[]; unique: boolean }[];
			columns: {
				name: string;
				data_type: string;
				is_primary_key: boolean;
				is_unique: boolean;
				is_nullable: boolean;
				note: string | null;
			}[];
			column_notes: Record<string, string>;
		}) => {
			if (!editingNodeId) return;
			setSavingTable(true);
			pushHistory();
			const editing = nodesRef.current.find((node) => node.id === editingNodeId);
			// A catalog table's schema mirrors the database: its note and its
			// per-column aliases are the only things the canvas owns.
			const payload = editing?.table_id
				? { note: patch.note, column_notes: patch.column_notes }
				: patch;
			void erdApi.updateNode(editingNodeId, payload).then((response) => {
				setSavingTable(false);
				if (response.error || !response.data) {
					setError(response.message ?? t('Failed to save the table'));
					return;
				}
				const updated = response.data;
				setNodes((current) =>
					current.map((node) => (node.id === updated.id ? updated : node)),
				);
				setEditingNodeId(null);
			});
		},
		[editingNodeId, pushHistory],
	);

	/**
	 * Apply one batch of assistant edits.
	 *
	 * The whole batch is a single undo step: `pushHistory()` runs once, before
	 * the first write, and the canvas is re-read afterwards so the board shows
	 * exactly what the server holds (including hidden catalog tombstones the
	 * batch may have created). Individual failures are counted rather than
	 * thrown — one impossible edit must not discard the twelve that worked.
	 */
	const applyAssistantActions = useCallback(
		async (actions: ErdAssistantAction[]) => {
			if (!zoneId || readOnly || !canvas || actions.length === 0) {
				return { applied: 0, failed: 0 };
			}
			pushHistory();

			// Track what each write returns so two edits to the same table in one
			// batch build on each other instead of overwriting one another.
			const working = nodesRef.current.map((node) => ({ ...node }));
			const findNode = (nodeId: string | null | undefined) =>
				working.find((node) => node.id === nodeId);

			let applied = 0;
			let failed = 0;
			let placed = 0;

			for (const action of actions) {
				let ok = false;
				try {
					switch (action.kind) {
						case 'create_table': {
							const response = await erdApi.createNode({
								canvas_id: canvas.id,
								name: action.name as string,
								columns: (action.columns ?? []).map((column) => ({
									name: column.name,
									data_type: column.data_type ?? 'text',
								})),
								note: action.note ?? null,
								x: action.x ?? 80 + (placed % 3) * 300,
								y: action.y ?? 80 + Math.floor(placed / 3) * 260,
							});
							placed += 1;
							if (response.data) {
								working.push(response.data);
								ok = true;
							}
							break;
						}
						case 'add_column': {
							const node = findNode(action.node_id);
							if (!node) break;
							const response = await erdApi.updateNode(node.id, {
								columns: [
									...node.columns.map((column) => ({
										name: column.name,
										data_type: column.data_type ?? 'text',
										is_primary_key: column.is_primary_key,
										is_unique: column.is_unique ?? undefined,
										is_nullable: column.is_nullable ?? undefined,
										note: column.note ?? null,
									})),
									{
										name: action.name as string,
										data_type: action.data_type ?? 'text',
										is_primary_key: false,
										is_unique: false,
										is_nullable: true,
										note: action.note ?? null,
									},
								],
							});
							if (response.data) {
								node.columns = response.data.columns;
								ok = true;
							}
							break;
						}
						case 'update_column': {
							const node = findNode(action.node_id);
							if (!node) break;
							if (node.table_id) {
								// A catalog column belongs to the source database; its alias
								// is the only part the canvas owns.
								if (!action.note) break;
								const response = await erdApi.updateNode(node.id, {
									column_notes: { [action.column as string]: action.note },
								});
								if (response.data) {
									node.columns = response.data.columns;
									ok = true;
								}
								break;
							}
							const response = await erdApi.updateNode(node.id, {
								columns: node.columns.map((column) =>
									column.name === action.column
										? {
												name: column.name,
												data_type:
													action.data_type ?? column.data_type ?? 'text',
												is_primary_key: column.is_primary_key,
												is_unique: column.is_unique ?? undefined,
												is_nullable: column.is_nullable ?? undefined,
												note: action.note ?? column.note ?? null,
											}
										: {
												name: column.name,
												data_type: column.data_type ?? 'text',
												is_primary_key: column.is_primary_key,
												is_unique: column.is_unique ?? undefined,
												is_nullable: column.is_nullable ?? undefined,
												note: column.note ?? null,
											},
								),
							});
							if (response.data) {
								node.columns = response.data.columns;
								ok = true;
							}
							break;
						}
						case 'rename_table':
						case 'set_table_note':
						case 'move_node': {
							const node = findNode(action.node_id);
							if (!node) break;
							const patch =
								action.kind === 'rename_table'
									? { name: action.name as string }
									: action.kind === 'set_table_note'
										? { note: action.note ?? '' }
										: { x: action.x ?? node.x, y: action.y ?? node.y };
							const response = await erdApi.updateNode(node.id, patch);
							if (response.data) {
								Object.assign(node, response.data);
								ok = true;
							}
							break;
						}
						case 'delete_table': {
							const response = await erdApi.deleteNode(action.node_id as string);
							ok = !response.error;
							break;
						}
						case 'bind_relationship': {
							const response = await erdApi.createRelationship({
								canvas_id: canvas.id,
								source_node_id: action.source_node_id as string,
								target_node_id: action.target_node_id as string,
								source_columns: action.source_columns ?? [],
								target_columns: action.target_columns ?? [],
								cardinality: action.cardinality ?? 'one-to-one',
								label: action.label ?? null,
							});
							ok = !response.error;
							break;
						}
						case 'delete_relationship': {
							const response = await erdApi.deleteRelationship(
								action.relationship_id as string,
							);
							ok = !response.error;
							break;
						}
						default:
							break;
					}
				} catch {
					ok = false;
				}
				if (ok) applied += 1;
				else failed += 1;
			}

			// One read at the end: the server is the authority on what the batch
			// actually produced (order, ids, hidden tombstones).
			const refreshed = await erdApi.getCanvas(zoneId);
			if (refreshed.data) {
				setCanvas(refreshed.data);
				setNodes(refreshed.data.nodes);
				setNotes(refreshed.data.notes);
				setAreas(refreshed.data.areas);
				setSelectedNodeIds(new Set());
				setSelectedRelationshipId(null);
			}

			return { applied, failed };
		},
		[canvas, pushHistory, readOnly, zoneId],
	);

	const selectedRelationship =
		canvas?.relationships.find((rel) => rel.id === selectedRelationshipId) ?? null;
	const nodeById = new Map(nodes.map((node) => [node.id, node]));
	const issues = useMemo(
		() => validateCanvas(nodes, canvas?.relationships ?? []),
		[nodes, canvas],
	);
	const errorCount = issues.filter((issue) => issue.severity === 'error').length;

	const handleFocusIssue = useCallback((issue: ErdIssue) => {
		if (issue.relationshipId) {
			setSelectedRelationshipId(issue.relationshipId);
			return;
		}
		const node = nodesRef.current.find((row) => row.id === issue.nodeId);
		if (node) setSearch(node.name);
	}, []);
	// A zone switch leaves the previous canvas mounted until its own answer
	// arrives; showing that one under the new zone's name would be a lie.
	const showSpinner =
		error == null && (loading || (zoneId != null && canvas?.zone_id !== zoneId));

	return (
		<div className="relative flex h-full min-h-0 flex-col bg-white dark:bg-zinc-950">
			<ErdToolbar
				zones={zones}
				zoneId={zoneId}
				onZoneChange={handleZoneChange}
				search={search}
				onSearchChange={setSearch}
				readOnly={readOnly}
				zoom={viewport.zoom}
				onAddTable={() => setAddOpen(true)}
				onAutoArrange={handleAutoArrange}
				onUndo={undo}
				onRedo={redo}
				canUndo={historyCounts.undo > 0}
				canRedo={historyCounts.redo > 0}
				issueCount={issues.length}
				errorCount={errorCount}
				snapToGrid={snapToGrid}
				onToggleSnap={() => setSnapToGrid((value) => !value)}
				showMinimap={showMinimap}
				onToggleMinimap={() => setShowMinimap((value) => !value)}
				canPaste={clipboardCount > 0}
				onPaste={() => void handlePaste()}
				onCopy={handleCopySelected}
				onOpenVersions={openVersions}
				onOpenTemplates={() => setTemplatesOpen(true)}
				onOpenIssues={() => {
					setIssuesOpen((open) => !open);
					setHiddenOpen(false);
				}}
				selectedCount={selectedNodeIds.size}
				onAddNote={handleAddNote}
				onAddArea={handleAddArea}
				onDuplicate={handleDuplicateSelected}
				onDeleteSelected={handleDeleteSelected}
				hiddenCount={canvas?.hidden_nodes.length ?? 0}
				onOpenHidden={() => {
					setHiddenOpen((open) => !open);
					setIssuesOpen(false);
				}}
				onOpenTransfer={() => setTransferOpen(true)}
				onZoomIn={() => canvasRef.current?.zoomIn()}
				onZoomOut={() => canvasRef.current?.zoomOut()}
				onFit={() => canvasRef.current?.fit()}
			/>

			{error && (
				<div className="flex items-center justify-between border-b border-red-200 bg-red-50 px-4 py-2 text-xs text-red-700 dark:border-red-800 dark:bg-red-950/40 dark:text-red-200">
					<span>{error}</span>
					<button type="button" onClick={() => setError(null)} aria-label={t('Dismiss')}>
						✕
					</button>
				</div>
			)}

			<div className="relative min-h-0 flex-1">
				{showSpinner ? (
					<div className="flex h-full items-center justify-center" role="status">
						<Spinner />
					</div>
				) : zones.length === 0 ? (
					<EmptyState
						title={t('No zones yet')}
						description={t(
							'A canvas is drawn per zone. Create a zone in Settings first.',
						)}
						action={{
							label: t('Open zone settings'),
							onClick: () => router.push('/settings/zones'),
						}}
					/>
				) : (
					<>
						<ErdCanvas
							ref={canvasRef}
							nodes={nodes}
							relationships={canvas?.relationships ?? []}
							viewport={viewport}
							readOnly={readOnly}
							search={search}
							selectedRelationshipId={selectedRelationshipId}
							selectedNodeIds={selectedNodeIds}
							notes={notes}
							areas={areas}
							snapToGrid={snapToGrid}
							showMinimap={showMinimap}
							onViewportChange={handleViewportChange}
							onNodeSelect={handleNodeSelect}
							onClearSelection={handleClearSelection}
							onNodesMove={handleNodesMove}
							onNodeDragStart={pushHistory}
							onNodesMoveEnd={handleNodesMoveEnd}
							onToggleCollapse={handleToggleCollapse}
							onEditNode={setEditingNodeId}
							onDeleteNode={handleDeleteNode}
							onReorderColumns={handleReorderColumns}
							onNodeResizeStart={pushHistory}
							onNodeResize={handleNodeResize}
							onNodeResizeEnd={handleNodeResizeEnd}
							onConnect={handleConnect}
							onSelectRelationship={setSelectedRelationshipId}
							onNoteDragStart={pushHistory}
							onNoteMove={handleNoteMove}
							onNoteMoveEnd={handleNoteMoveEnd}
							onNoteResize={handleNoteResize}
							onNoteResizeEnd={handleNoteResizeEnd}
							onNoteTextChange={handleNoteTextChange}
							onNoteTextCommit={handleNoteTextCommit}
							onNoteDelete={handleNoteDelete}
							onAreaDragStart={pushHistory}
							onAreaMove={handleAreaMove}
							onAreaMoveEnd={handleAreaMoveEnd}
							onAreaResize={handleAreaResize}
							onAreaResizeEnd={handleAreaResizeEnd}
							onAreaRename={handleAreaRename}
							onAreaDelete={handleAreaDelete}
						/>
						{nodes.length === 0 && (
							<div className="pointer-events-none absolute inset-0 flex items-center justify-center p-8">
								<div className="pointer-events-auto max-w-md rounded-2xl border border-dashed border-zinc-300 bg-white/80 p-8 text-center backdrop-blur dark:border-zinc-600 dark:bg-zinc-900/80">
									<p className="text-sm font-medium text-body dark:text-zinc-200">
										{t('This zone has no tables yet')}
									</p>
									<p className="mt-1 text-xs text-secondary dark:text-zinc-400">
										{t(
											'Add tables to the zone, import a DBML/JSON document, or draw a table by hand.',
										)}
									</p>
									{!readOnly && (
										<div className="mt-3 flex justify-center gap-2">
											<Button
												theme={ButtonTheme.Secondary}
												size={Size.SMALL}
												onClick={() => setAddOpen(true)}
											>
												{t('Add table')}
											</Button>
											<Button
												theme={ButtonTheme.Secondary}
												size={Size.SMALL}
												onClick={() => setTransferOpen(true)}
											>
												{t('Import')}
											</Button>
										</div>
									)}
								</div>
							</div>
						)}
						{selectedRelationship && (
							<RelationshipPanel
								key={selectedRelationship.id}
								relationship={selectedRelationship}
								source={nodeById.get(selectedRelationship.source_node_id)}
								target={nodeById.get(selectedRelationship.target_node_id)}
								readOnly={readOnly}
								onChange={handleRelationshipChange}
								onDelete={handleDeleteRelationship}
								onClose={() => setSelectedRelationshipId(null)}
							/>
						)}
						{issuesOpen && (
							<ValidationPanel
								issues={issues}
								readOnly={readOnly}
								onClose={() => setIssuesOpen(false)}
								onFocus={handleFocusIssue}
								onDeleteRelationship={deleteRelationshipById}
							/>
						)}
						{hiddenOpen && (
							<div className="absolute right-4 top-4 z-20 w-72 rounded-xl border border-zinc-200 bg-white shadow-lg dark:border-zinc-700 dark:bg-zinc-900">
								<div className="flex items-center justify-between border-b border-zinc-200 px-3 py-2 dark:border-zinc-700">
									<span className="text-xs font-semibold text-heading dark:text-zinc-200">
										{t('Hidden tables')} ({canvas?.hidden_nodes.length ?? 0})
									</span>
									<Button
										theme={ButtonTheme.IconNeutral}
										size={Size.SMALL}
										iconOnly
										onClick={() => setHiddenOpen(false)}
										aria-label={t('Close')}
									>
										✕
									</Button>
								</div>
								<ul className="max-h-64 overflow-y-auto p-2">
									{(canvas?.hidden_nodes ?? []).map((hidden) => (
										<li
											key={hidden.id}
											className="flex items-center justify-between gap-2 rounded-lg px-1 py-1.5 text-xs text-body dark:text-zinc-300"
										>
											<span className="min-w-0 truncate" title={hidden.name}>
												{hidden.name}
											</span>
											{!readOnly && (
												<Button
													theme={ButtonTheme.Minimal}
													size={Size.SMALL}
													onClick={() => handleRestoreNode(hidden.id)}
												>
													{t('Restore')}
												</Button>
											)}
										</li>
									))}
								</ul>
							</div>
						)}
					</>
				)}
			</div>

			{transferOpen && (
				<ImportExportDialog
					open
					readOnly={readOnly}
					busy={busy}
					warnings={warnings}
					onClose={() => setTransferOpen(false)}
					onImport={handleImport}
					onExport={handleExport}
					onExportImage={handleExportImage}
				/>
			)}
			{addOpen && (
				<AddTableDialog open onClose={() => setAddOpen(false)} onCreate={handleAddTable} />
			)}
			{editingNode && (
				<TableEditorDialog
					node={editingNode}
					busy={savingTable}
					onClose={() => setEditingNodeId(null)}
					onSave={handleSaveTable}
				/>
			)}
			<ConfirmDialog request={confirmRequest} onClose={() => setConfirmRequest(null)} />
			<VersionsDialog
				open={versionsOpen}
				versions={versions}
				busy={versionsBusy}
				readOnly={readOnly}
				onClose={() => setVersionsOpen(false)}
				onCreate={handleCreateVersion}
				onRestore={handleRestoreVersion}
				onDelete={handleDeleteVersion}
			/>
			<TemplatesDialog
				open={templatesOpen}
				busy={templatesBusy}
				readOnly={readOnly}
				onClose={() => setTemplatesOpen(false)}
				onInsert={(template) => void handleInsertTemplate(template)}
			/>
			<ErdAssistant
				zoneId={zoneId}
				readOnly={readOnly}
				nodes={nodes}
				relationships={canvas?.relationships ?? []}
				onApply={applyAssistantActions}
			/>
		</div>
	);
};
