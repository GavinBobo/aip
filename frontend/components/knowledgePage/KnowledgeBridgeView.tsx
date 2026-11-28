// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useCallback, useEffect, useState, type ReactNode } from 'react';
import Link from 'next/link';

import {
	knowledgeApi,
	type KnowledgeBridge,
	type KnowledgeDataTarget,
	type KnowledgeNetwork,
} from '@/api/knowledge';
import { sqlAttributesApi } from '@/api/sqlAttributes';
import { Button } from '@/common/Button';
import { Icon, IconName } from '@/common/icons';
import { Modal } from '@/common/modal/Modal';
import { Spinner } from '@/common/Spinner';
import { ButtonTheme, Size } from '@/enums/button';
import { t } from '@/i18n';
import type { SqlAttribute } from '@/types/terms';

const inputClassName =
	'h-9 w-full rounded-md border border-zinc-300 bg-white px-3 text-sm text-body outline-none transition-colors focus:border-[#76b900] focus:ring-2 focus:ring-[#76b900]/30 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200';

const CoverageCard = ({
	label,
	linked,
	total,
}: {
	label: string;
	linked: number;
	total: number;
}) => {
	const percent = total > 0 ? Math.round((linked / total) * 100) : 0;
	return (
		<div className="rounded-xl border border-zinc-200 bg-zinc-50 p-4 dark:border-zinc-700 dark:bg-zinc-900/60">
			<div className="text-[10px] font-semibold uppercase tracking-wide text-secondary dark:text-zinc-400">
				{label}
			</div>
			<div className="mt-1 text-2xl font-semibold text-heading dark:text-zinc-100">
				{linked}/{total}
			</div>
			<div className="mt-2 h-1.5 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-700">
				<div
					className="h-full rounded-full bg-[#76b900]"
					style={{ width: `${percent}%` }}
				/>
			</div>
		</div>
	);
};

const Section = ({
	title,
	description,
	children,
}: {
	title: string;
	description: string;
	children: ReactNode;
}) => (
	<section className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-700 dark:bg-zinc-900">
		<h2 className="text-base font-semibold text-heading dark:text-zinc-100">{title}</h2>
		<p className="mt-1 text-xs leading-5 text-secondary dark:text-zinc-400">{description}</p>
		<div className="mt-4 flex flex-col gap-2">{children}</div>
	</section>
);

export const KnowledgeBridgeView = () => {
	const [networks, setNetworks] = useState<KnowledgeNetwork[]>([]);
	const [networkId, setNetworkId] = useState('');
	const [bridge, setBridge] = useState<KnowledgeBridge | null>(null);
	const [sqlAttributes, setSqlAttributes] = useState<SqlAttribute[]>([]);
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [mappingId, setMappingId] = useState<string | null>(null);
	const [ruleOpen, setRuleOpen] = useState(false);
	const [ruleSaving, setRuleSaving] = useState(false);
	const [ruleForm, setRuleForm] = useState({
		name: '',
		statement: '',
		scope: '',
		condition: '',
		roles: '',
	});
	const [targetQuery, setTargetQuery] = useState<Record<string, string>>({});
	const [targetResults, setTargetResults] = useState<Record<string, KnowledgeDataTarget[]>>({});

	useEffect(() => {
		let cancelled = false;
		knowledgeApi.listNetworks().then((response) => {
			if (cancelled || response.error || !response.data) return;
			setNetworks(response.data);
			setNetworkId((current) => current || response.data?.[0]?.id || '');
		});
		sqlAttributesApi.list().then((response) => {
			if (!cancelled && !response.error && response.data) {
				setSqlAttributes(response.data);
			}
		});
		return () => {
			cancelled = true;
		};
	}, []);

	const loadBridge = useCallback(async (id: string) => {
		if (!id) return;
		setLoading(true);
		setError(null);
		const response = await knowledgeApi.getBridge(id);
		setLoading(false);
		if (response.error || !response.data) {
			setError(response.message ?? t('Failed to load the semantic bridge.'));
			setBridge(null);
			return;
		}
		setBridge(response.data);
	}, []);

	useEffect(() => {
		const id = window.setTimeout(() => {
			void loadBridge(networkId);
		}, 0);
		return () => window.clearTimeout(id);
	}, [networkId, loadBridge]);

	const searchTargets = async (conceptId: string) => {
		const query = (targetQuery[conceptId] ?? '').trim();
		if (!query) return;
		const response = await knowledgeApi.dataTargets(query);
		if (response.data) {
			setTargetResults((current) => ({
				...current,
				[conceptId]: response.data ?? [],
			}));
		}
	};

	const linkConcept = async (conceptId: string, target: KnowledgeDataTarget) => {
		setMappingId(conceptId);
		const response = await knowledgeApi.linkConcept(conceptId, {
			target_kind: target.kind === 'table' ? 'table' : 'term',
			target_id: target.id,
		});
		setMappingId(null);
		if (response.error) {
			setError(response.message ?? t('Failed to link the concept.'));
			return;
		}
		setTargetResults((current) => ({ ...current, [conceptId]: [] }));
		await loadBridge(networkId);
	};

	const linkMetric = async (metricId: string, attributeId: string) => {
		if (!attributeId) return;
		setMappingId(metricId);
		const response = await knowledgeApi.updateMetric(metricId, {
			sql_attribute_id: attributeId,
		});
		setMappingId(null);
		if (response.error) {
			setError(response.message ?? t('Failed to link the metric.'));
			return;
		}
		await loadBridge(networkId);
	};

	const linkAction = async (actionId: string, capabilityId: string) => {
		if (!capabilityId) return;
		setMappingId(actionId);
		const response = await knowledgeApi.linkActionCapability(actionId, capabilityId);
		setMappingId(null);
		if (response.error) {
			setError(response.message ?? t('Failed to link the action.'));
			return;
		}
		await loadBridge(networkId);
	};

	const linkRule = async (ruleId: string, targetKind: 'metric' | 'action', targetId: string) => {
		if (!targetId) return;
		setMappingId(ruleId);
		const response = await knowledgeApi.linkRule(ruleId, {
			target_kind: targetKind,
			target_id: targetId,
		});
		setMappingId(null);
		if (response.error) {
			setError(response.message ?? t('Failed to link the rule.'));
			return;
		}
		await loadBridge(networkId);
	};

	const createRule = async () => {
		if (!networkId || !ruleForm.name.trim() || !ruleForm.statement.trim()) return;
		setRuleSaving(true);
		const response = await knowledgeApi.createRule(networkId, {
			name: ruleForm.name.trim(),
			statement: ruleForm.statement.trim(),
			scope: ruleForm.scope.trim() || undefined,
			condition: ruleForm.condition.trim() || undefined,
			roles: ruleForm.roles
				.split(',')
				.map((item) => item.trim())
				.filter(Boolean),
		});
		setRuleSaving(false);
		if (response.error) {
			setError(response.message ?? t('Failed to create the rule.'));
			return;
		}
		setRuleOpen(false);
		setRuleForm({ name: '', statement: '', scope: '', condition: '', roles: '' });
		await loadBridge(networkId);
	};

	const selectedNetwork = networks.find((network) => network.id === networkId);

	return (
		<div className="flex h-full w-full flex-col overflow-y-auto bg-white dark:bg-zinc-950">
			<header className="border-b border-zinc-200 px-6 py-6 dark:border-zinc-800">
				<div className="flex flex-wrap items-start justify-between gap-4">
					<div>
						<div className="flex items-center gap-2">
							<Icon name={IconName.Link} className="h-5 w-5 text-[#76b900]" />
							<h1 className="text-xl font-semibold tracking-tight text-heading dark:text-zinc-100">
								{t('Semantic bridge')}
							</h1>
						</div>
						<p className="mt-2 max-w-3xl text-sm leading-6 text-secondary dark:text-zinc-400">
							{t(
								'Connect document concepts to terms or tables, knowledge metrics to SQL attributes, and actions to executable capabilities.',
							)}
						</p>
					</div>
					<div className="flex items-center gap-2">
						<select
							value={networkId}
							onChange={(event) => setNetworkId(event.target.value)}
							aria-label={t('Knowledge network')}
							className="h-9 max-w-64 rounded-lg border border-zinc-300 bg-white px-2 text-sm text-body outline-none focus:border-[#76b900] dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
						>
							{networks.map((network) => (
								<option key={network.id} value={network.id}>
									{network.name}
								</option>
							))}
						</select>
						{selectedNetwork && (
							<Link
								href={`/knowledge/${encodeURIComponent(selectedNetwork.id)}`}
								className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-zinc-300 bg-white px-3 text-sm font-medium text-body no-underline hover:border-[#76b900] dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
							>
								<Icon name={IconName.Knowledge} className="h-4 w-4" />
								{t('Open network')}
							</Link>
						)}
					</div>
				</div>
			</header>

			<main className="flex-1 px-6 py-5">
				{error && (
					<div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300">
						{error}
					</div>
				)}
				{loading ? (
					<div className="flex h-48 items-center justify-center">
						<Spinner />
					</div>
				) : !bridge ? (
					<div className="rounded-2xl border border-dashed border-zinc-300 bg-zinc-50/60 px-8 py-12 text-center dark:border-zinc-700 dark:bg-zinc-900/60">
						<p className="text-sm text-secondary dark:text-zinc-400">
							{t('Select a knowledge network to inspect its semantic bridge.')}
						</p>
					</div>
				) : (
					<div className="flex flex-col gap-5">
						<div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
							<CoverageCard
								label={t('Overall coverage')}
								linked={
									bridge.summary.concept_linked +
									bridge.summary.metric_linked +
									bridge.summary.rule_linked +
									bridge.summary.action_linked
								}
								total={
									bridge.summary.concept_total +
									bridge.summary.metric_total +
									bridge.summary.rule_total +
									bridge.summary.action_total
								}
							/>
							<CoverageCard
								label={t('Concepts linked')}
								linked={bridge.summary.concept_linked}
								total={bridge.summary.concept_total}
							/>
							<CoverageCard
								label={t('Metrics linked')}
								linked={bridge.summary.metric_linked}
								total={bridge.summary.metric_total}
							/>
							<CoverageCard
								label={t('Rules linked')}
								linked={bridge.summary.rule_linked}
								total={bridge.summary.rule_total}
							/>
							<CoverageCard
								label={t('Actions linked')}
								linked={bridge.summary.action_linked}
								total={bridge.summary.action_total}
							/>
						</div>

						<Section
							title={t('Concepts to terms and tables')}
							description={t(
								'Map a document concept to the glossary term or catalog table it describes.',
							)}
						>
							{bridge.concepts.length === 0 ? (
								<p className="text-sm text-secondary dark:text-zinc-400">
									{t('No concepts in this network.')}
								</p>
							) : (
								bridge.concepts.map((concept) => (
									<div
										key={concept.id}
										className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-700"
									>
										<div className="flex flex-wrap items-center gap-2">
											<span className="text-sm font-medium text-heading dark:text-zinc-100">
												{concept.name}
											</span>
											<span className="rounded-md bg-zinc-100 px-1.5 py-0.5 text-[10px] text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
												{concept.kind || t('Unknown')}
											</span>
											<span
												className={`ml-auto text-[11px] ${
													concept.linked
														? 'text-emerald-600 dark:text-emerald-400'
														: 'text-amber-600 dark:text-amber-400'
												}`}
											>
												{concept.linked ? t('Linked') : t('Unlinked')}
											</span>
										</div>
										{concept.linked ? (
											<div className="mt-2 flex flex-wrap gap-1.5">
												{concept.links.map((item) => (
													<span
														key={item.id}
														className="rounded-md border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-300"
													>
														{item.kind}: {item.name}
													</span>
												))}
											</div>
										) : (
											<div className="mt-2 flex flex-wrap items-center gap-2">
												<input
													className={`${inputClassName} max-w-sm`}
													value={targetQuery[concept.id] ?? ''}
													onChange={(event) =>
														setTargetQuery((current) => ({
															...current,
															[concept.id]: event.target.value,
														}))
													}
													placeholder={t('Search term or catalog table')}
													onKeyDown={(event) => {
														if (event.key === 'Enter') {
															event.preventDefault();
															void searchTargets(concept.id);
														}
													}}
												/>
												<Button
													theme={ButtonTheme.Secondary}
													size={Size.SMALL}
													type="button"
													onClick={() => void searchTargets(concept.id)}
												>
													{t('Search')}
												</Button>
												{(targetResults[concept.id] ?? []).map((target) => (
													<Button
														key={`${target.kind}:${target.id}`}
														theme={ButtonTheme.Soft}
														size={Size.SMALL}
														type="button"
														loading={mappingId === concept.id}
														onClick={() =>
															void linkConcept(concept.id, target)
														}
													>
														{target.kind}: {target.name}
													</Button>
												))}
											</div>
										)}
									</div>
								))
							)}
						</Section>

						<Section
							title={t('Rules to metrics and actions')}
							description={t(
								'Link a rule to the metrics it evaluates and the actions it triggers. A rule is not a metric.',
							)}
						>
							<div className="flex justify-end">
								<Button
									theme={ButtonTheme.Secondary}
									size={Size.SMALL}
									type="button"
									onClick={() => setRuleOpen(true)}
								>
									{t('New rule')}
								</Button>
							</div>
							{bridge.rules.length === 0 ? (
								<p className="text-sm text-secondary dark:text-zinc-400">
									{t('No rules in this network.')}
								</p>
							) : (
								bridge.rules.map((rule) => (
									<div
										key={rule.id}
										className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-700"
									>
										<div className="flex flex-wrap items-center gap-2">
											<span className="text-sm font-medium text-heading dark:text-zinc-100">
												{rule.name}
											</span>
											<span
												className={`ml-auto text-[11px] ${
													rule.linked
														? 'text-emerald-600 dark:text-emerald-400'
														: 'text-amber-600 dark:text-amber-400'
												}`}
											>
												{rule.linked ? t('Linked') : t('Unlinked')}
											</span>
										</div>
										<p className="mt-1 text-xs leading-5 text-secondary dark:text-zinc-400">
											{rule.statement}
										</p>
										<div className="mt-2 flex flex-wrap items-center gap-2">
											{rule.metrics.map((metric) => (
												<span
													key={`metric:${metric.id}`}
													className="rounded-md border border-cyan-200 bg-cyan-50 px-2 py-1 text-[11px] text-cyan-700 dark:border-cyan-800 dark:bg-cyan-950/30 dark:text-cyan-300"
												>
													{t('Metric')}: {metric.name}
												</span>
											))}
											{rule.actions.map((action) => (
												<span
													key={`action:${action.id}`}
													className="rounded-md border border-violet-200 bg-violet-50 px-2 py-1 text-[11px] text-violet-700 dark:border-violet-800 dark:bg-violet-950/30 dark:text-violet-300"
												>
													{t('Action')}: {action.name}
												</span>
											))}
											{rule.metrics.length === 0 && (
												<select
													className="h-8 max-w-xs rounded-md border border-zinc-300 bg-white px-2 text-[11px] text-body dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
													defaultValue=""
													disabled={mappingId === rule.id}
													onChange={(event) =>
														void linkRule(
															rule.id,
															'metric',
															event.target.value,
														)
													}
												>
													<option value="">{t('Select metric')}</option>
													{bridge.metrics.map((metric) => (
														<option key={metric.id} value={metric.id}>
															{metric.name}
														</option>
													))}
												</select>
											)}
											{rule.actions.length === 0 && (
												<select
													className="h-8 max-w-xs rounded-md border border-zinc-300 bg-white px-2 text-[11px] text-body dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
													defaultValue=""
													disabled={mappingId === rule.id}
													onChange={(event) =>
														void linkRule(
															rule.id,
															'action',
															event.target.value,
														)
													}
												>
													<option value="">{t('Select action')}</option>
													{bridge.actions.map((action) => (
														<option key={action.id} value={action.id}>
															{action.name}
														</option>
													))}
												</select>
											)}
										</div>
									</div>
								))
							)}
						</Section>

						<Section
							title={t('Metrics to SQL attributes')}
							description={t(
								'Attach a knowledge metric to the reviewed SQL expression that computes it.',
							)}
						>
							{bridge.metrics.length === 0 ? (
								<p className="text-sm text-secondary dark:text-zinc-400">
									{t('No metrics in this network.')}
								</p>
							) : (
								bridge.metrics.map((metric) => (
									<div
										key={metric.id}
										className="flex flex-wrap items-center gap-2 rounded-lg border border-zinc-200 p-3 dark:border-zinc-700"
									>
										<div className="min-w-48 flex-1">
											<div className="text-sm font-medium text-heading dark:text-zinc-100">
												{metric.name}
											</div>
											<div className="text-[11px] text-secondary dark:text-zinc-400">
												{metric.expression || t('No expression')}
												{metric.unit ? ` · ${metric.unit}` : ''}
											</div>
										</div>
										{metric.linked ? (
											<span className="rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1 text-[11px] text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-300">
												{metric.sql_attribute_name ||
													metric.sql_attribute_id}
											</span>
										) : (
											<select
												className="h-9 max-w-sm rounded-md border border-zinc-300 bg-white px-2 text-xs text-body dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
												defaultValue=""
												disabled={mappingId === metric.id}
												onChange={(event) =>
													void linkMetric(metric.id, event.target.value)
												}
											>
												<option value="">
													{t('Select SQL attribute')}
												</option>
												{sqlAttributes.map((attribute) => (
													<option key={attribute.id} value={attribute.id}>
														{attribute.name}
														{attribute.term_name
															? ` · ${attribute.term_name}`
															: ''}
													</option>
												))}
											</select>
										)}
									</div>
								))
							)}
						</Section>

						<Section
							title={t('Actions to capabilities')}
							description={t(
								'Attach an executable action to a mounted Skill, Function, MCP tool or knowledge base.',
							)}
						>
							{bridge.actions.length === 0 ? (
								<p className="text-sm text-secondary dark:text-zinc-400">
									{t('No actions in this network.')}
								</p>
							) : (
								bridge.actions.map((action) => (
									<div
										key={action.id}
										className="flex flex-wrap items-center gap-2 rounded-lg border border-zinc-200 p-3 dark:border-zinc-700"
									>
										<div className="min-w-48 flex-1">
											<div className="text-sm font-medium text-heading dark:text-zinc-100">
												{action.name}
											</div>
											<div className="text-[11px] text-secondary dark:text-zinc-400">
												{action.capabilities.length
													? action.capabilities
															.map((capability) => capability.name)
															.join(', ')
													: t('No capability mounted')}
											</div>
										</div>
										{!action.linked && (
											<select
												className="h-9 max-w-sm rounded-md border border-zinc-300 bg-white px-2 text-xs text-body dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
												defaultValue=""
												disabled={mappingId === action.id}
												onChange={(event) =>
													void linkAction(action.id, event.target.value)
												}
											>
												<option value="">{t('Select capability')}</option>
												{bridge.capabilities.map((capability) => (
													<option
														key={capability.id}
														value={capability.id}
													>
														{capability.name} · {capability.kind}
													</option>
												))}
											</select>
										)}
									</div>
								))
							)}
						</Section>
					</div>
				)}
			</main>

			<Modal
				open={ruleOpen}
				onClose={() => setRuleOpen(false)}
				className="w-full max-w-xl overflow-hidden"
				ariaLabel={t('New rule')}
			>
				<header className="flex items-center justify-between border-b border-zinc-200 px-5 py-4 dark:border-zinc-700">
					<h2 className="text-base font-semibold text-heading dark:text-zinc-100">
						{t('New rule')}
					</h2>
					<Button
						theme={ButtonTheme.IconNeutral}
						size={Size.SMALL}
						iconOnly
						type="button"
						onClick={() => setRuleOpen(false)}
						aria-label={t('Close')}
					>
						<Icon name={IconName.Close} className="h-4 w-4" />
					</Button>
				</header>
				<div className="space-y-3 p-5">
					<input
						className={inputClassName}
						value={ruleForm.name}
						onChange={(event) =>
							setRuleForm((current) => ({ ...current, name: event.target.value }))
						}
						placeholder={t('Rule name')}
						autoFocus
					/>
					<textarea
						className="min-h-24 w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-body outline-none focus:border-[#76b900] focus:ring-2 focus:ring-[#76b900]/30 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-200"
						value={ruleForm.statement}
						onChange={(event) =>
							setRuleForm((current) => ({
								...current,
								statement: event.target.value,
							}))
						}
						placeholder={t('Rule statement')}
					/>
					<div className="grid gap-3 sm:grid-cols-2">
						<input
							className={inputClassName}
							value={ruleForm.scope}
							onChange={(event) =>
								setRuleForm((current) => ({
									...current,
									scope: event.target.value,
								}))
							}
							placeholder={t('Scope (optional)')}
						/>
						<input
							className={inputClassName}
							value={ruleForm.condition}
							onChange={(event) =>
								setRuleForm((current) => ({
									...current,
									condition: event.target.value,
								}))
							}
							placeholder={t('Condition (optional)')}
						/>
					</div>
					<input
						className={inputClassName}
						value={ruleForm.roles}
						onChange={(event) =>
							setRuleForm((current) => ({ ...current, roles: event.target.value }))
						}
						placeholder={t('Roles (comma separated)')}
					/>
				</div>
				<footer className="flex justify-end gap-2 border-t border-zinc-200 px-5 py-4 dark:border-zinc-700">
					<Button
						theme={ButtonTheme.Secondary}
						type="button"
						onClick={() => setRuleOpen(false)}
					>
						{t('Cancel')}
					</Button>
					<Button
						loading={ruleSaving}
						disabled={!ruleForm.name.trim() || !ruleForm.statement.trim()}
						type="button"
						onClick={() => void createRule()}
					>
						{t('Create rule')}
					</Button>
				</footer>
			</Modal>
		</div>
	);
};
