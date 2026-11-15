// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { ErdCardinality } from '@/types/erd';

export type TemplateColumn = {
	name: string;
	data_type: string;
	is_primary_key?: boolean;
	is_unique?: boolean;
	is_nullable?: boolean;
};

export type TemplateTable = {
	name: string;
	columns: TemplateColumn[];
	note?: string;
	indexes?: { name: string | null; columns: string[]; unique: boolean }[];
};

export type TemplateRelationship = {
	source: string;
	target: string;
	source_columns: string[];
	target_columns: string[];
	cardinality: ErdCardinality;
};

export type TableTemplate = {
	id: string;
	name: string;
	description: string;
	tables: TemplateTable[];
	relationships: TemplateRelationship[];
};

/**
 * Starter shapes for the modelling canvas. Deliberately small and generic:
 * they exist to get a diagram going, not to model anybody's domain.
 */
export const TABLE_TEMPLATES: TableTemplate[] = [
	{
		id: 'customers-orders',
		name: 'Customers & orders',
		description: 'Customer master, orders and order lines with foreign keys.',
		tables: [
			{
				name: 'public.customers',
				note: 'One row per customer account.',
				columns: [
					{ name: 'id', data_type: 'bigint', is_primary_key: true },
					{ name: 'name', data_type: 'varchar(120)' },
					{ name: 'email', data_type: 'varchar(200)', is_unique: true },
					{ name: 'created_at', data_type: 'timestamp', is_nullable: false },
				],
				indexes: [{ name: 'ix_customers_email', columns: ['email'], unique: true }],
			},
			{
				name: 'public.orders',
				columns: [
					{ name: 'id', data_type: 'bigint', is_primary_key: true },
					{ name: 'customer_id', data_type: 'bigint', is_nullable: false },
					{ name: 'ordered_at', data_type: 'timestamp', is_nullable: false },
					{ name: 'status', data_type: 'varchar(32)' },
				],
			},
			{
				name: 'public.order_items',
				columns: [
					{ name: 'id', data_type: 'bigint', is_primary_key: true },
					{ name: 'order_id', data_type: 'bigint', is_nullable: false },
					{ name: 'product_name', data_type: 'varchar(200)' },
					{ name: 'quantity', data_type: 'integer', is_nullable: false },
					{ name: 'unit_price', data_type: 'numeric(12,2)' },
				],
			},
		],
		relationships: [
			{
				source: 'public.orders',
				target: 'public.customers',
				source_columns: ['customer_id'],
				target_columns: ['id'],
				cardinality: 'many-to-one',
			},
			{
				source: 'public.order_items',
				target: 'public.orders',
				source_columns: ['order_id'],
				target_columns: ['id'],
				cardinality: 'many-to-one',
			},
		],
	},
	{
		id: 'event-log',
		name: 'Event log',
		description: 'Append-only events with an actor and a JSON payload.',
		tables: [
			{
				name: 'public.events',
				columns: [
					{ name: 'id', data_type: 'uuid', is_primary_key: true },
					{ name: 'event_type', data_type: 'varchar(64)', is_nullable: false },
					{ name: 'occurred_at', data_type: 'timestamp', is_nullable: false },
					{ name: 'actor_id', data_type: 'uuid' },
					{ name: 'payload', data_type: 'jsonb' },
				],
				indexes: [
					{
						name: 'ix_events_occurred_at',
						columns: ['occurred_at'],
						unique: false,
					},
				],
			},
		],
		relationships: [],
	},
	{
		id: 'star-dimensions',
		name: 'Date & product dimensions',
		description: 'Two small dimensions to hang facts off.',
		tables: [
			{
				name: 'public.dim_date',
				columns: [
					{ name: 'date_key', data_type: 'date', is_primary_key: true },
					{ name: 'year', data_type: 'integer', is_nullable: false },
					{ name: 'month', data_type: 'integer', is_nullable: false },
					{ name: 'day', data_type: 'integer', is_nullable: false },
				],
			},
			{
				name: 'public.dim_product',
				columns: [
					{ name: 'product_key', data_type: 'bigint', is_primary_key: true },
					{ name: 'sku', data_type: 'varchar(64)', is_unique: true },
					{ name: 'name', data_type: 'varchar(200)' },
					{ name: 'category', data_type: 'varchar(100)' },
				],
			},
		],
		relationships: [],
	},
];
