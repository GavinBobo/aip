// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';

import { erdApi } from '@/api/erd';
import { Button } from '@/common/Button';
import { Modal } from '@/common/modal/Modal';
import { ButtonTheme, Size } from '@/enums/button';
import { t } from '@/i18n';
import type {
	ErdOntologyApplyResult,
	ErdOntologyEntity,
	ErdOntologyIssue,
	ErdOntologyRelationship,
	ErdOntologyReport,
} from '@/types/erd';

type ErdOntologyDialogProps = {
	open: boolean;
	zoneId: string | null;
	readOnly: boolean;
	onClose: () => void;
	onApplied?: () => void;
};

type Tab = 'entities' | 'relationships' | 'gaps';

const STATUS_STYLES: Record<string, string> = {
	ready: 'border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-300',
	existing:
		'border-sky-300 bg-sky-50 text-sky-700 dark:border-sky-800 dark:bg-sky-950/30 dark:text-sky-300',
	virtual:
		'border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-300',
	needs_review:
		'border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-300',
	validated:
		'border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-300',
	declared:
		'border-sky-300 bg-sky-50 text-sky-700 dark:border-sky-800 dark:bg-sky-950/30 dark:text-sky-300',
	probable:
		'border-indigo-300 bg-indigo-50 text-indigo-700 dark:border-indigo-800 dark:bg-indigo-950/30 dark:text-indigo-300',
	logical_only:
		'border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-300',
	invalid:
		'border-red-300 bg-red-50 text-red-700 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300',
};

const SEVERITY_STYLES: Record<string, string> = {
	info: 'border-zinc-200 bg-zinc-50 text-zinc-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300',
	warning:
		'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-300',
	error: 'border-red-200 bg-red-50 text-red-700 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300',
};

const statusLabel = (status: string) =>
	t(
		status === 'ready'
			? 'Ready'
			: status === 'existing'
				? 'Existing'
				: status === 'virtual'
					? 'Virtual'
					: status === 'needs_review'
						? 'Needs review'
						: status === 'validated'
							? 'Validated'
							: status === 'declared'
								? 'Declared'
								: status === 'probable'
									? 'Probable'
									: status === 'logical_only'
										? 'Logical only'
										: 'Invalid',
	);

const roleLabel = (role: string) =>
	t(
		role === 'fact'
			? 'Fact'
			: role === 'dimension'
				? 'Dimension'
				: role === 'bridge'
					? 'Bridge'
					: role === 'staging'
						? 'Staging'
						: role === 'lookup'
							? 'Lookup'
							: 'Unknown',
	);

const issueText = (issue: ErdOntologyIssue): string => {
	const params = issue.params ?? {};
	switch (issue.code) {
		case 'virtual_table':
			return t(
				'Virtual table “{table}” is not queryable until it is bound to a catalog table.',
				{ table: String(params.table ?? '') },
			);
		case 'missing_term':
			return t('No semantic Term is linked to {table} yet.', {
				table: String(params.table ?? ''),
			});
		case 'term_missing_description':
			return t('The Term “{term}” has no business description.', {
				term: String(params.term ?? ''),
			});
		case 'table_missing_description':
			return t('Neither the catalog nor the ERD explains what {table} represents.', {
				table: String(params.table ?? ''),
			});
		case 'table_missing_primary_key':
			return t('{table} has no primary key; its row grain is unknown.', {
				table: String(params.table ?? ''),
			});
		case 'table_missing_columns':
			return t('{table} has no columns to model.', {
				table: String(params.table ?? ''),
			});
		case 'category_missing':
			return t('{table} has no ERD category; its semantic role was inferred.', {
				table: String(params.table ?? ''),
			});
		case 'possible_pii':
			return t('Possible personal data in: {columns}. Verify their PII tags.', {
				columns: String(params.columns ?? ''),
			});
		case 'relationship_virtual_endpoint':
			return t('This relationship has a diagram-only endpoint and cannot be applied.');
		case 'relationship_many_to_many':
			return t(
				'A many-to-many relationship needs a junction table before it can become a semantic foreign key.',
			);
		case 'relationship_missing_columns':
			return t('This relationship has no column pair to validate.');
		case 'relationship_composite_key':
			return t(
				'Composite key pairs are applied as individual semantic FK edges; verify the join semantics.',
			);
		case 'relationship_missing_columns_in_catalog':
			return t('These relationship columns are missing: {columns}.', {
				columns: String(params.columns ?? ''),
			});
		case 'relationship_type_mismatch':
			return t('The two sides have incompatible data types.');
		case 'relationship_target_not_unique':
			return t('The referenced columns are not a primary or unique key.');
		case 'relationship_not_declared':
			return t('The catalog does not declare this foreign key; it is ERD-only.');
		case 'relationship_not_profiled':
			return t('No sampled values are available to check key overlap.');
		case 'relationship_value_overlap_empty':
			return t('The sampled key values on the two sides do not overlap.');
		case 'catalog_fk_not_in_erd':
			return t('The catalog declares a foreign key that the ERD does not draw.');
		default:
			return issue.message;
	}
};

const StatusPill = ({ status }: { status: string }) => (
	<span
		className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
			STATUS_STYLES[status] ?? SEVERITY_STYLES.info
		}`}
	>
		{statusLabel(status)}
	</span>
);

const IssueLine = ({ issue }: { issue: ErdOntologyIssue }) => (
	<p className={`rounded-md border px-2 py-1 text-[11px] ${SEVERITY_STYLES[issue.severity]}`}>
		{issueText(issue)}
	</p>
);

const CheckChip = ({ label, value }: { label: string; value: boolean | null | undefined }) => (
	<span
		className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] ${
			value === true
				? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-300'
				: value === false
					? 'border-red-200 bg-red-50 text-red-700 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300'
					: 'border-zinc-200 bg-zinc-50 text-zinc-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-400'
		}`}
	>
		{label}
		{value === true ? ' ✓' : value === false ? ' ×' : ' ?'}
	</span>
);

const EntityRow = ({
	entity,
	checked,
	onToggle,
}: {
	entity: ErdOntologyEntity;
	checked: boolean;
	onToggle: () => void;
}) => (
	<label className="flex cursor-pointer gap-3 rounded-xl border border-zinc-200 bg-white p-3 transition-colors hover:border-zinc-300 dark:border-zinc-700 dark:bg-zinc-900 dark:hover:border-zinc-600">
		<input
			type="checkbox"
			checked={checked}
			disabled={!entity.apply.can_apply}
			onChange={onToggle}
			className="mt-1 h-4 w-4 accent-[#76b900] disabled:opacity-40"
		/>
		<div className="min-w-0 flex-1">
			<div className="flex flex-wrap items-center gap-2">
				<span className="truncate text-sm font-semibold text-heading dark:text-zinc-100">
					{entity.name}
				</span>
				<StatusPill status={entity.status} />
				<span className="rounded-md bg-zinc-100 px-1.5 py-0.5 text-[10px] text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
					{roleLabel(entity.semantic_role)}
				</span>
				<span className="ml-auto text-[11px] text-zinc-500 dark:text-zinc-400">
					{Math.round(entity.confidence * 100)}%
				</span>
			</div>
			<div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-secondary dark:text-zinc-400">
				<span>
					{t('Proposed Term')}: {entity.proposed_term?.name || '—'}
				</span>
				<span>
					{t('Columns')}: {entity.columns.length}
				</span>
				<span>
					{t('Primary key')}:{' '}
					{entity.primary_keys.length ? entity.primary_keys.join(', ') : t('None')}
				</span>
				<span>
					{t('Attributes')}: {entity.existing_column_attributes}
				</span>
				<span>
					{t('Semantic FKs')}: {entity.existing_semantic_fks}
				</span>
			</div>
			{entity.warnings.length > 0 && (
				<div className="mt-2 flex flex-col gap-1">
					{entity.warnings.slice(0, 2).map((issue, index) => (
						<IssueLine key={`${issue.code}-${index}`} issue={issue} />
					))}
					{entity.warnings.length > 2 && (
						<span className="text-[10px] text-zinc-500 dark:text-zinc-400">
							{t('+{count} more warnings', { count: entity.warnings.length - 2 })}
						</span>
					)}
				</div>
			)}
		</div>
	</label>
);

const RelationshipRow = ({
	relationship,
	checked,
	onToggle,
}: {
	relationship: ErdOntologyRelationship;
	checked: boolean;
	onToggle: () => void;
}) => (
	<label className="flex cursor-pointer gap-3 rounded-xl border border-zinc-200 bg-white p-3 transition-colors hover:border-zinc-300 dark:border-zinc-700 dark:bg-zinc-900 dark:hover:border-zinc-600">
		<input
			type="checkbox"
			checked={checked}
			disabled={!relationship.apply.can_apply}
			onChange={onToggle}
			className="mt-1 h-4 w-4 accent-[#76b900] disabled:opacity-40"
		/>
		<div className="min-w-0 flex-1">
			<div className="flex flex-wrap items-center gap-2">
				<span className="truncate text-sm font-semibold text-heading dark:text-zinc-100">
					{relationship.source_table} → {relationship.target_table}
				</span>
				<StatusPill status={relationship.status} />
				<span className="rounded-md bg-zinc-100 px-1.5 py-0.5 text-[10px] text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
					{relationship.cardinality}
				</span>
				<span className="ml-auto text-[11px] text-zinc-500 dark:text-zinc-400">
					{Math.round(relationship.confidence * 100)}%
				</span>
			</div>
			<div className="mt-1 text-[11px] text-secondary dark:text-zinc-400">
				{relationship.referencing_columns.join(', ') || '—'} →{' '}
				{relationship.referenced_columns.join(', ') || '—'}
				{relationship.label ? ` · ${relationship.label}` : ''}
			</div>
			<div className="mt-2 flex flex-wrap gap-1">
				<CheckChip label={t('Catalog FK')} value={relationship.checks.catalog_fk} />
				<CheckChip label={t('Type')} value={relationship.checks.type_compatible} />
				<CheckChip label={t('Unique')} value={relationship.checks.target_unique} />
				<CheckChip
					label={`${t('Values')}${
						relationship.checks.value_overlap == null
							? ''
							: ` ${Math.round(relationship.checks.value_overlap * 100)}%`
					}`}
					value={
						relationship.checks.value_overlap == null
							? null
							: relationship.checks.value_overlap > 0
					}
				/>
				{relationship.existing_semantic_fk && (
					<span className="rounded-md border border-sky-200 bg-sky-50 px-1.5 py-0.5 text-[10px] text-sky-700 dark:border-sky-800 dark:bg-sky-950/30 dark:text-sky-300">
						{t('Existing semantic FK')}
					</span>
				)}
			</div>
			{relationship.warnings.length > 0 && (
				<div className="mt-2 flex flex-col gap-1">
					{relationship.warnings.slice(0, 2).map((issue, index) => (
						<IssueLine key={`${issue.code}-${index}`} issue={issue} />
					))}
				</div>
			)}
		</div>
	</label>
);

export const ErdOntologyDialog = ({
	open,
	zoneId,
	readOnly,
	onClose,
	onApplied,
}: ErdOntologyDialogProps) => {
	const [report, setReport] = useState<ErdOntologyReport | null>(null);
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [tab, setTab] = useState<Tab>('entities');
	const [selectedEntities, setSelectedEntities] = useState<Set<string>>(new Set());
	const [selectedRelationships, setSelectedRelationships] = useState<Set<string>>(new Set());
	const [createTerms, setCreateTerms] = useState(true);
	const [createSemanticFks, setCreateSemanticFks] = useState(true);
	const [applying, setApplying] = useState(false);
	const [applyResult, setApplyResult] = useState<ErdOntologyApplyResult | null>(null);

	const load = useCallback(async () => {
		if (!zoneId) return;
		setLoading(true);
		setError(null);
		const response = await erdApi.getOntologyCandidates(zoneId);
		if (response.error || !response.data) {
			setError(response.message ?? t('Failed to build data ontology candidates.'));
			setReport(null);
			setLoading(false);
			return;
		}
		setReport(response.data);
		setSelectedEntities(
			new Set(
				response.data.entities
					.filter((entity) => entity.apply.can_apply)
					.map((entity) => entity.id),
			),
		);
		setSelectedRelationships(
			new Set(
				response.data.relationships
					.filter((relationship) => relationship.apply.can_apply)
					.map((relationship) => relationship.id),
			),
		);
		setLoading(false);
	}, [zoneId]);

	useEffect(() => {
		if (!open || !zoneId) return;
		// The effect only schedules the read; setting state in the effect body
		// would make React report a cascading render.
		const id = window.setTimeout(() => {
			void load();
		}, 0);
		return () => window.clearTimeout(id);
	}, [open, zoneId, load]);

	const handleClose = () => {
		setTab('entities');
		setApplyResult(null);
		onClose();
	};

	const selectedCount = selectedEntities.size + selectedRelationships.size;
	const applyableRelationships = useMemo(
		() =>
			report?.relationships.filter((relationship) => relationship.apply.can_apply).length ??
			0,
		[report],
	);

	const toggle = (set: Set<string>, id: string) => {
		const next = new Set(set);
		if (next.has(id)) next.delete(id);
		else next.add(id);
		return next;
	};

	const handleApply = async () => {
		if (!zoneId || selectedCount === 0) return;
		setApplying(true);
		setError(null);
		const response = await erdApi.applyOntologyCandidates(zoneId, {
			entity_node_ids: [...selectedEntities],
			relationship_ids: [...selectedRelationships],
			create_terms: createTerms,
			create_semantic_fks: createSemanticFks,
		});
		if (response.error || !response.data) {
			setError(response.message ?? t('Failed to apply data ontology candidates.'));
			setApplying(false);
			return;
		}
		setApplyResult(response.data);
		setApplying(false);
		onApplied?.();
		void load();
	};

	return (
		<Modal
			open={open}
			onClose={handleClose}
			className="flex max-h-[88vh] w-full max-w-6xl flex-col overflow-hidden"
			ariaLabel={t('Data ontology candidates')}
		>
			<header className="flex items-start justify-between gap-4 border-b border-zinc-200 px-5 py-4 dark:border-zinc-700">
				<div>
					<h2 className="text-base font-semibold text-heading dark:text-zinc-100">
						{t('Data ontology candidates')}
					</h2>
					<p className="mt-1 text-xs text-secondary dark:text-zinc-400">
						{t(
							'Review what this ERD and the catalog imply before writing anything to the semantic layer.',
						)}
					</p>
				</div>
				<Button
					theme={ButtonTheme.IconNeutral}
					size={Size.SMALL}
					iconOnly
					type="button"
					onClick={handleClose}
					aria-label={t('Close')}
				>
					✕
				</Button>
			</header>

			<div className="min-h-0 flex-1 overflow-y-auto p-5">
				{loading ? (
					<div className="flex h-48 items-center justify-center text-sm text-secondary dark:text-zinc-400">
						{t('Building candidates…')}
					</div>
				) : error ? (
					<div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300">
						{error}
					</div>
				) : report ? (
					<div className="flex flex-col gap-5">
						<div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
							{[
								{
									label: t('Readiness'),
									value: `${Math.round(report.summary.readiness * 100)}%`,
									detail:
										report.summary.readiness_label === 'ready'
											? t('Ready')
											: report.summary.readiness_label === 'review'
												? t('Needs review')
												: t('Early'),
								},
								{
									label: t('Mapped tables'),
									value: `${report.summary.mapped_node_count}/${report.summary.node_count}`,
									detail: t('{count} virtual', {
										count: report.summary.virtual_node_count,
									}),
								},
								{
									label: t('Terms'),
									value: `${report.summary.term_count}/${report.summary.mapped_node_count}`,
									detail: t('{count} described', {
										count: report.summary.description_count,
									}),
								},
								{
									label: t('Relationships'),
									value: `${report.summary.validated_relationship_count}/${report.summary.relationship_count}`,
									detail: t('Validated'),
								},
								{
									label: t('Issues'),
									value: String(report.summary.issue_count),
									detail: t('{count} gaps', { count: report.summary.gap_count }),
								},
							].map((card) => (
								<div
									key={card.label}
									className="rounded-xl border border-zinc-200 bg-zinc-50 p-3 dark:border-zinc-700 dark:bg-zinc-900/60"
								>
									<div className="text-[10px] font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
										{card.label}
									</div>
									<div className="mt-1 text-xl font-semibold text-heading dark:text-zinc-100">
										{card.value}
									</div>
									<div className="text-[11px] text-secondary dark:text-zinc-400">
										{card.detail}
									</div>
								</div>
							))}
						</div>

						{applyResult && (
							<div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-300">
								<span className="font-semibold">{t('Applied')}</span>{' '}
								{t('{terms} terms created, {fks} semantic FKs created.', {
									terms: applyResult.terms_created.length,
									fks: applyResult.semantic_fks_created.length,
								})}{' '}
								{applyResult.skipped.length > 0 &&
									t('{count} skipped', { count: applyResult.skipped.length })}
								{applyResult.errors.length > 0 &&
									` · ${t('{count} errors', { count: applyResult.errors.length })}`}
							</div>
						)}

						<div className="flex flex-wrap items-center gap-2 border-b border-zinc-200 pb-2 dark:border-zinc-700">
							{(
								[
									['entities', t('Entities'), report.entities.length],
									[
										'relationships',
										t('Relationships'),
										report.relationships.length,
									],
									['gaps', t('Gaps'), report.gaps.length],
								] as [Tab, string, number][]
							).map(([id, label, count]) => (
								<button
									key={id}
									type="button"
									onClick={() => setTab(id)}
									className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
										tab === id
											? 'bg-[#76b900]/15 text-[#4d7a00] dark:text-[#a3d63a]'
											: 'text-secondary hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800'
									}`}
								>
									{label} <span className="opacity-70">{count}</span>
								</button>
							))}
							{(tab === 'entities' || tab === 'relationships') && !readOnly && (
								<div className="ml-auto flex gap-2 text-[11px]">
									<button
										type="button"
										onClick={() => {
											if (tab === 'entities') {
												setSelectedEntities(
													new Set(
														report.entities
															.filter(
																(entity) => entity.apply.can_apply,
															)
															.map((entity) => entity.id),
													),
												);
											} else {
												setSelectedRelationships(
													new Set(
														report.relationships
															.filter(
																(relationship) =>
																	relationship.apply.can_apply,
															)
															.map((relationship) => relationship.id),
													),
												);
											}
										}}
										className="text-[#4d7a00] hover:underline dark:text-[#a3d63a]"
									>
										{t('Select all')}
									</button>
									<button
										type="button"
										onClick={() =>
											tab === 'entities'
												? setSelectedEntities(new Set())
												: setSelectedRelationships(new Set())
										}
										className="text-secondary hover:underline dark:text-zinc-400"
									>
										{t('Clear')}
									</button>
								</div>
							)}
						</div>

						{tab === 'entities' && (
							<div className="flex flex-col gap-2">
								{report.entities.length === 0 ? (
									<p className="py-8 text-center text-sm text-secondary dark:text-zinc-400">
										{t('No table candidates on this canvas.')}
									</p>
								) : (
									report.entities.map((entity) => (
										<EntityRow
											key={entity.id}
											entity={entity}
											checked={selectedEntities.has(entity.id)}
											onToggle={() =>
												setSelectedEntities((current) =>
													toggle(current, entity.id),
												)
											}
										/>
									))
								)}
							</div>
						)}

						{tab === 'relationships' && (
							<div className="flex flex-col gap-2">
								{report.relationships.length === 0 ? (
									<p className="py-8 text-center text-sm text-secondary dark:text-zinc-400">
										{t('No relationship candidates on this canvas.')}
									</p>
								) : (
									report.relationships.map((relationship) => (
										<RelationshipRow
											key={relationship.id}
											relationship={relationship}
											checked={selectedRelationships.has(relationship.id)}
											onToggle={() =>
												setSelectedRelationships((current) =>
													toggle(current, relationship.id),
												)
											}
										/>
									))
								)}
							</div>
						)}

						{tab === 'gaps' && (
							<div className="flex flex-col gap-2">
								{report.gaps.length === 0 ? (
									<p className="py-8 text-center text-sm text-secondary dark:text-zinc-400">
										{t('No gaps found.')}
									</p>
								) : (
									report.gaps.map((gap, index) => (
										<div
											key={`${gap.code}-${index}`}
											className={`rounded-lg border p-3 text-xs ${SEVERITY_STYLES[gap.severity]}`}
										>
											<div className="font-semibold uppercase tracking-wide">
												{gap.severity}
											</div>
											<div className="mt-1">{issueText(gap)}</div>
										</div>
									))
								)}
							</div>
						)}
					</div>
				) : null}
			</div>

			{report && !readOnly && (
				<footer className="flex flex-wrap items-center gap-3 border-t border-zinc-200 bg-zinc-50 px-5 py-3 dark:border-zinc-700 dark:bg-zinc-900/60">
					<label className="flex items-center gap-2 text-xs text-body dark:text-zinc-300">
						<input
							type="checkbox"
							checked={createTerms}
							onChange={(event) => setCreateTerms(event.target.checked)}
							className="h-4 w-4 accent-[#76b900]"
						/>
						{t('Create terms')}
					</label>
					<label className="flex items-center gap-2 text-xs text-body dark:text-zinc-300">
						<input
							type="checkbox"
							checked={createSemanticFks}
							onChange={(event) => setCreateSemanticFks(event.target.checked)}
							className="h-4 w-4 accent-[#76b900]"
						/>
						{t('Create semantic FKs')}
					</label>
					<span className="text-[11px] text-secondary dark:text-zinc-400">
						{t('{count} selected', { count: selectedCount })}
						{applyableRelationships > 0 &&
							` · ${t('{count} applyable relationships', {
								count: applyableRelationships,
							})}`}
					</span>
					<div className="ml-auto flex gap-2">
						<Button
							theme={ButtonTheme.Secondary}
							size={Size.REGULAR}
							type="button"
							onClick={handleClose}
						>
							{t('Close')}
						</Button>
						<Button
							theme={ButtonTheme.Primary}
							size={Size.REGULAR}
							type="button"
							loading={applying}
							disabled={selectedCount === 0}
							onClick={() => void handleApply()}
						>
							{t('Apply selected')}
						</Button>
					</div>
				</footer>
			)}
		</Modal>
	);
};
