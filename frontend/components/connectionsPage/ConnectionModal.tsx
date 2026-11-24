// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useCallback, useMemo, useState } from 'react';
import { connectionsApi } from '@/api/connections';
import { ModalWithSteps, type StepperFooterAction } from '@/common/modal';
import { ConnectionConnectStep } from '@/components/connectionsPage/steps/ConnectionConnectStep';
import {
	FileConnectionStep,
	type FileSourceMode,
} from '@/components/connectionsPage/steps/FileConnectionStep';
import { ConnectionSelectDataStep } from '@/components/connectionsPage/steps/ConnectionSelectDataStep';
import {
	connectionNameErrorMessage,
	isValidConnectionName,
	RESERVED_CONNECTION_NAMES,
} from '@/components/connectionsPage/connection-name';
import { t } from '@/i18n';
import { ConnectionTypeStep } from '@/components/connectionsPage/steps/ConnectionTypeStep';
import {
	ApiConnectionStep,
	EMPTY_API_FORM,
	type ApiFormValues,
} from '@/components/connectionsPage/steps/ApiConnectionStep';
import {
	CONNECTION_EITHER_FIELDS,
	connectionFieldsFor,
	ConnectionType,
	type ConnectionFieldKey,
} from '@/enums/connection';
import type {
	ApiConnectionParams,
	ApiPreview,
	Connection,
	ConnectionInput,
	ConnectionParams,
	FilePreview,
	ServerPathListing,
} from '@/types/connection';

const TYPE_STEP = 'Select Connector';
const CONNECT_STEP = 'Connect';
const SCHEMA_STEP = 'Select Schemas';
const FILE_STEP = 'Prepare Data';
const API_STEP = 'Request';

/** Separator choices offered by the file step; '' means detect it. */
const DELIMITER_PRESETS = ['', ',', '\t', ';', '|', ' '] as const;

/**
 * Connectors whose backend honours a `schemas` ingestion allowlist and returns a
 * schema list from the connection test. Types absent here skip the picker step
 * and ingest everything the credentials can see.
 */
const SCHEMA_SELECTION_TYPES: ReadonlySet<ConnectionType> = new Set([
	ConnectionType.DATABRICKS,
	ConnectionType.MSSQL,
	ConnectionType.SNOWFLAKE,
	ConnectionType.KYUUBI,
	ConnectionType.TRINO,
]);

type FieldValues = Partial<Record<ConnectionFieldKey, string>>;

/** The form stores every value as a string; a checkbox is 'true'/''. */
const toFieldValue = (raw: unknown): string => {
	if (typeof raw === 'boolean') return raw ? 'true' : '';
	return typeof raw === 'string' ? raw : '';
};

const toFieldValues = (params: ConnectionParams): FieldValues => {
	const stored = params as Record<string, unknown>;
	return Object.fromEntries(
		connectionFieldsFor(params.type)
			.filter((field) => stored[field.key] != null)
			.map((field) => [field.key, toFieldValue(stored[field.key])]),
	);
};

/** Column names implied by *row* of a preview, deduplicated the way the
 * backend will dedupe them, so the form shows what will actually be stored. */
const namesFromRow = (preview: FilePreview, row: number): string[] => {
	const values = preview.rows[row] ?? [];
	const seen = new Set<string>();
	return Array.from({ length: preview.column_count }, (_, index) => {
		const base = (values[index] ?? '').trim() || t('Column {0}', { 0: index + 1 });
		let name = base;
		let suffix = 2;
		while (seen.has(name.toLowerCase())) {
			name = `${base}_${suffix}`;
			suffix += 1;
		}
		seen.add(name.toLowerCase());
		return name;
	});
};

/** Turn a file name into the identifier the connection name has to be. */
const defaultConnectionName = (fileName: string): string => {
	const stem = fileName.replace(/\.[^.]+$/, '');
	let name = stem.replace(/[^0-9A-Za-z_]+/g, '_').replace(/^_+|_+$/g, '');
	if (name === '') name = 'dataset';
	if (/^[0-9]/.test(name)) name = `t_${name}`;
	if (RESERVED_CONNECTION_NAMES.has(name.toLowerCase())) name = `${name}_dataset`;
	return name.slice(0, 64);
};

const connectionNameProblem = connectionNameErrorMessage;

/** Stored JSON settings rendered for a textarea; empty objects become blank. */
const jsonText = (value: unknown): string => {
	if (value == null) return '';
	if (typeof value === 'string') return value;
	if (typeof value === 'object' && Object.keys(value as object).length === 0) return '';
	return JSON.stringify(value, null, 2);
};

const apiFormFromStored = (stored: ApiConnectionParams | null): ApiFormValues => ({
	...EMPTY_API_FORM,
	database: stored?.database ?? '',
	url: stored?.url ?? '',
	method: stored?.method ?? t('GET'),
	headers: jsonText(stored?.headers),
	params: jsonText(stored?.params),
	body: jsonText(stored?.body),
	recordsPath: stored?.records_path ?? '',
	authType: stored?.auth_type ?? 'none',
	user: stored?.user ?? '',
	timeout: String(stored?.timeout_s ?? 30),
});

export type ConnectionModalProps = {
	open: boolean;
	/**
	 * Editing when set. The connector type and database name are the connection's
	 * identity on the backend, so both are fixed for the life of the record.
	 */
	connection?: Connection | null;
	/**
	 * Skip the connector picker when the caller has already chosen a kind, as
	 * the page's dedicated "Connect API" action does. Ignored while editing.
	 */
	initialType?: ConnectionType | null;
	onConfirm: () => void;
	onCancel: () => void;
};

export const ConnectionModal = ({
	open,
	connection = null,
	initialType = null,
	onConfirm,
	onCancel,
}: ConnectionModalProps) => {
	const editing = connection != null;

	const [loading, setLoading] = useState(false);
	const [testingConnection, setTestingConnection] = useState(false);
	const [isConnectionTested, setIsConnectionTested] = useState(false);
	const [testSuccessMessage, setTestSuccessMessage] = useState<string | null>(null);
	// A preset type lands on its own step; the picker is only shown when the
	// caller has not expressed a preference.
	const [activeStep, setActiveStep] = useState(connection == null && initialType != null ? 1 : 0);
	const [connectionType, setConnectionType] = useState<ConnectionType>(
		connection?.connection.type ?? initialType ?? ConnectionType.POSTGRESQL,
	);
	const [values, setValues] = useState<FieldValues>(() =>
		connection == null ? {} : toFieldValues(connection.connection),
	);
	const [alert, setAlert] = useState<string | null>(null);

	// File connections keep their own state: the wizard collects a name, the
	// file, the header row and the column names instead of connection fields.
	const storedFile =
		connection?.connection.type === ConnectionType.FILE ? connection.connection : null;
	const [fileDatabase, setFileDatabase] = useState(storedFile?.database ?? '');
	const [filePreview, setFilePreview] = useState<FilePreview | null>(null);
	const [selectedFile, setSelectedFile] = useState<File | null>(null);
	const [fileBusy, setFileBusy] = useState(false);
	const [fileError, setFileError] = useState<string | null>(null);
	const [fileSheet, setFileSheet] = useState<string | null>(storedFile?.sheet ?? null);
	const storedDelimiter = storedFile?.delimiter ?? '';
	const [fileDelimiter, setFileDelimiter] = useState<string>(
		(DELIMITER_PRESETS as readonly string[]).includes(storedDelimiter)
			? storedDelimiter
			: 'custom',
	);
	const [customDelimiter, setCustomDelimiter] = useState<string>(
		(DELIMITER_PRESETS as readonly string[]).includes(storedDelimiter) ? ',' : storedDelimiter,
	);
	const [fileHeaderRow, setFileHeaderRow] = useState(storedFile?.header_row ?? 0);
	const [fileColumns, setFileColumns] = useState<string[]>(storedFile?.columns ?? []);
	/** One flag per preview column; unchecked columns are not materialised. */
	const [fileKeep, setFileKeep] = useState<boolean[]>([]);
	// A file can arrive through a browser upload or from a shared folder the
	// backend can already read. Editing remembers which one it came from.
	const [fileSourceMode, setFileSourceMode] = useState<FileSourceMode>(
		storedFile?.source_path ? 'server' : 'upload',
	);
	const [serverPath, setServerPath] = useState(storedFile?.source_path ?? '');

	// REST API connections: request settings plus the fetched preview.
	const storedApi =
		connection?.connection.type === ConnectionType.API ? connection.connection : null;
	const [apiValues, setApiValues] = useState<ApiFormValues>(() => apiFormFromStored(storedApi));
	const [apiPreview, setApiPreview] = useState<ApiPreview | null>(null);
	const [apiColumns, setApiColumns] = useState<string[]>(
		storedApi?.columns.map((column) => column.name) ?? [],
	);
	const [apiBusy, setApiBusy] = useState(false);
	const [apiError, setApiError] = useState<string | null>(null);
	const [apiFetchedAt, setApiFetchedAt] = useState<string | null>(storedApi?.fetched_at ?? null);

	// The stored allowlist is what the picker reopens on, and what a re-test
	// falls back to rather than silently dropping the connection's scope.
	const initialSchemas = useMemo(
		() => (connection?.connection as { schemas?: string[] } | undefined)?.schemas ?? [],
		[connection],
	);

	// `availableSchemas` is populated from the connection-test response, so
	// there's no separate fetch.
	const [availableSchemas, setAvailableSchemas] = useState<string[]>([]);
	const [selectedSchemas, setSelectedSchemas] = useState<string[]>(initialSchemas);

	/**
	 * Credentials are stripped from everything the API hands back, so an edit
	 * form cannot show them. Blank therefore means "keep the stored one", which
	 * is how the backend reads it too.
	 */
	const keepCurrentKeys = useMemo<ReadonlySet<ConnectionFieldKey>>(() => {
		if (connection == null) return new Set();
		const stored = connection.connection as Record<string, unknown>;
		return new Set(
			connectionFieldsFor(connection.connection.type)
				.filter((field) => field.secret === true && stored[field.key] == null)
				.map((field) => field.key),
		);
	}, [connection]);

	const readOnlyKeys = useMemo<ReadonlySet<ConnectionFieldKey>>(
		() => (editing ? new Set<ConnectionFieldKey>(['database']) : new Set()),
		[editing],
	);

	const supportsSchemaSelection = SCHEMA_SELECTION_TYPES.has(connectionType);
	const isFileType = connectionType === ConnectionType.FILE;
	const isApiType = connectionType === ConnectionType.API;

	// Naming a schema on the form replaces picking one from a list: the test has
	// already confirmed it exists, so there is nothing left to choose.
	const explicitSchema = (values.schema ?? '').trim();

	const steps = useMemo(() => {
		// A file connection has no host/credentials to test: uploading the file
		// is the validation, so the wizard is just "pick the type, prepare it".
		if (isFileType) {
			return editing ? [FILE_STEP] : [TYPE_STEP, FILE_STEP];
		}
		if (isApiType) {
			return editing ? [API_STEP] : [TYPE_STEP, API_STEP];
		}
		const base = editing ? [CONNECT_STEP] : [TYPE_STEP, CONNECT_STEP];
		return supportsSchemaSelection && !explicitSchema ? [...base, SCHEMA_STEP] : base;
	}, [editing, isApiType, isFileType, supportsSchemaSelection, explicitSchema]);

	// `testOnly` fields (the Databricks schema filter) shape the connection test
	// but must not end up on the stored connection, so they are dropped unless
	// the payload is headed for the test endpoint.
	const buildConnection = useCallback(
		({ forTest = false }: { forTest?: boolean } = {}): ConnectionInput => {
			const fields = connectionFieldsFor(connectionType).filter(
				(field) => forTest || !field.testOnly,
			);
			const entries = fields.map((field) => [
				field.key,
				// Checkbox fields go over the wire as real booleans; the form
				// stores them as 'true'/'' like every other value.
				field.boolean ? values[field.key] === 'true' : (values[field.key] ?? '').trim(),
			]);
			const base = { type: connectionType, ...Object.fromEntries(entries) };
			if (supportsSchemaSelection) {
				// A named schema is the allowlist; otherwise use whatever was picked.
				if (explicitSchema) {
					return { ...base, schemas: [explicitSchema] } as ConnectionInput;
				}
				if (selectedSchemas.length > 0) {
					return { ...base, schemas: selectedSchemas } as ConnectionInput;
				}
			}
			return base as ConnectionInput;
		},
		[connectionType, values, supportsSchemaSelection, selectedSchemas, explicitSchema],
	);

	const fieldsComplete = useMemo(() => {
		const allRequiredPresent = connectionFieldsFor(connectionType).every(
			(field) =>
				field.optional ||
				keepCurrentKeys.has(field.key) ||
				(values[field.key] ?? '').trim().length > 0,
		);
		// Alternative credentials are each optional on their own, so the "every
		// required field" check above cannot see that one of them is still needed.
		const alternatives = CONNECTION_EITHER_FIELDS[connectionType];
		const alternativeSatisfied =
			alternatives == null ||
			alternatives.some(
				(key) => keepCurrentKeys.has(key) || (values[key] ?? '').trim().length > 0,
			);

		return allRequiredPresent && alternativeSatisfied;
	}, [connectionType, values, keepCurrentKeys]);

	const onTypeStep = steps[activeStep] === TYPE_STEP;
	const canContinue = onTypeStep ? false : fieldsComplete;

	const handleNext = useCallback((): void => {
		setAlert(null);
		setActiveStep((prev) => Math.min(prev + 1, steps.length - 1));
	}, [steps.length]);

	const handleBack = useCallback((): void => {
		setAlert(null);
		setActiveStep((prev) => Math.max(prev - 1, 0));
	}, []);

	const resetSchemaState = useCallback((): void => {
		setAvailableSchemas([]);
		setSelectedSchemas(initialSchemas);
	}, [initialSchemas]);

	const handleSelectType = (type: ConnectionType): void => {
		setConnectionType(type);
		setValues({});
		setAlert(null);
		setIsConnectionTested(false);
		setTestSuccessMessage(null);
		resetSchemaState();
		setFilePreview(null);
		setSelectedFile(null);
		setFileError(null);
		setFileDatabase('');
		setFileSheet(null);
		setFileDelimiter('');
		setCustomDelimiter(',');
		setFileHeaderRow(0);
		setFileColumns([]);
		setFileSourceMode('upload');
		setServerPath('');
		setApiValues(EMPTY_API_FORM);
		setApiPreview(null);
		setApiColumns([]);
		setApiError(null);
		setApiFetchedAt(null);
		setActiveStep(1);
	};

	const handleFieldChange = (key: ConnectionFieldKey, value: string): void => {
		setValues((prev) => ({ ...prev, [key]: value }));
		setIsConnectionTested(false);
		setTestSuccessMessage(null);
		setAlert(null);
		// Credentials changed — any previously fetched schemas are now stale.
		resetSchemaState();
	};

	const applyPreview = useCallback((preview: FilePreview): void => {
		setFilePreview(preview);
		setFileSheet(preview.sheet);
		setFileHeaderRow(preview.detected_header_row);
		setFileColumns(preview.column_names);
		setFileKeep(Array.from({ length: preview.column_count }, () => true));
		setFileError(null);
	}, []);

	// The character actually sent: the preset itself, or one character of the
	// custom box. '' lets the backend detect it.
	const effectiveDelimiter =
		fileDelimiter === 'custom' ? customDelimiter.slice(0, 1) : fileDelimiter;

	const loadPreview = useCallback(
		async (file: File, sheet?: string | null, delimiter?: string | null): Promise<void> => {
			setFileBusy(true);
			setFileError(null);
			setAlert(null);
			const res = await connectionsApi.previewFile(file, sheet, delimiter);
			setFileBusy(false);
			if ('error' in res && res.error) {
				setFilePreview(null);
				setFileColumns([]);
				setFileKeep([]);
				setFileError(res.message ?? t('Could not read the file.'));
				return;
			}
			applyPreview(res);
		},
		[applyPreview],
	);

	const loadServerPreview = useCallback(
		async (path: string, sheet?: string | null, delimiter?: string | null): Promise<void> => {
			const trimmed = path.trim();
			if (trimmed === '') {
				setFileError(t('Enter or browse to a file on the server.'));
				return;
			}
			setFileBusy(true);
			setFileError(null);
			setAlert(null);
			const res = await connectionsApi.previewServerFile(trimmed, sheet, delimiter);
			setFileBusy(false);
			if ('error' in res && res.error) {
				setFilePreview(null);
				setFileColumns([]);
				setFileKeep([]);
				setFileError(res.message ?? t('Could not read the file.'));
				return;
			}
			applyPreview(res);
			if (fileDatabase.trim() === '') {
				setFileDatabase(defaultConnectionName(res.filename));
			}
		},
		[applyPreview, fileDatabase],
	);

	const handleFileSourceModeChange = useCallback(
		(mode: FileSourceMode): void => {
			if (mode === fileSourceMode) return;
			setFileSourceMode(mode);
			setFilePreview(null);
			setFileSheet(null);
			setFileHeaderRow(0);
			setFileColumns([]);
			setFileKeep([]);
			setFileError(null);
			setAlert(null);
			if (mode === 'upload' && selectedFile != null) {
				void loadPreview(selectedFile, undefined, effectiveDelimiter);
			}
			if (mode === 'server' && serverPath.trim() !== '') {
				void loadServerPreview(serverPath, undefined, effectiveDelimiter);
			}
		},
		[
			effectiveDelimiter,
			fileSourceMode,
			loadPreview,
			loadServerPreview,
			selectedFile,
			serverPath,
		],
	);

	const handleServerPathChange = useCallback((path: string): void => {
		setServerPath(path);
		setFilePreview(null);
		setFileSheet(null);
		setFileHeaderRow(0);
		setFileColumns([]);
		setFileError(null);
	}, []);

	const handleLoadServerPath = useCallback(
		(path?: string): void => {
			void loadServerPreview(path ?? serverPath, fileSheet, effectiveDelimiter);
		},
		[effectiveDelimiter, fileSheet, loadServerPreview, serverPath],
	);

	const handleBrowseServerPaths = useCallback(
		async (path: string | null): Promise<ServerPathListing | { error: string }> => {
			const res = await connectionsApi.browseServerPaths(path);
			if ('error' in res && res.error) {
				return { error: res.message ?? t('Could not list the shared folders.') };
			}
			return res;
		},
		[],
	);

	const handleSelectFile = useCallback(
		(file: File): void => {
			setSelectedFile(file);
			// Default the catalog name to the file's stem; the operator can
			// change it until the connection is created.
			if (fileDatabase.trim() === '') {
				setFileDatabase(defaultConnectionName(file.name));
			}
			void loadPreview(file, undefined, effectiveDelimiter);
		},
		[effectiveDelimiter, fileDatabase, loadPreview],
	);

	const handleSheetChange = useCallback(
		(sheet: string): void => {
			setFileSheet(sheet);
			if (fileSourceMode === 'server' && serverPath.trim() !== '') {
				void loadServerPreview(serverPath, sheet, effectiveDelimiter);
			} else if (selectedFile != null) {
				void loadPreview(selectedFile, sheet, effectiveDelimiter);
			}
		},
		[
			effectiveDelimiter,
			fileSourceMode,
			loadPreview,
			loadServerPreview,
			selectedFile,
			serverPath,
		],
	);

	const handleDelimiterChange = useCallback(
		(value: string): void => {
			setFileDelimiter(value);
			const next = value === 'custom' ? customDelimiter.slice(0, 1) : value;
			if (fileSourceMode === 'server' && serverPath.trim() !== '') {
				void loadServerPreview(serverPath, fileSheet, next);
			} else if (selectedFile != null) {
				void loadPreview(selectedFile, fileSheet, next);
			}
		},
		[
			customDelimiter,
			fileSheet,
			fileSourceMode,
			loadPreview,
			loadServerPreview,
			selectedFile,
			serverPath,
		],
	);

	const handleCustomDelimiterChange = useCallback(
		(value: string): void => {
			setCustomDelimiter(value);
			if (value.length !== 1) return;
			if (fileSourceMode === 'server' && serverPath.trim() !== '') {
				void loadServerPreview(serverPath, fileSheet, value);
			} else if (selectedFile != null) {
				void loadPreview(selectedFile, fileSheet, value);
			}
		},
		[fileSheet, fileSourceMode, loadPreview, loadServerPreview, selectedFile, serverPath],
	);

	const handleHeaderRowChange = useCallback(
		(row: number): void => {
			setFileHeaderRow(row);
			if (filePreview != null) setFileColumns(namesFromRow(filePreview, row));
		},
		[filePreview],
	);

	const handleColumnNameChange = useCallback((index: number, name: string): void => {
		setFileColumns((previous) =>
			previous.map((value, position) => (position === index ? name : value)),
		);
	}, []);

	const handleColumnToggle = useCallback((index: number): void => {
		setFileKeep((previous) => {
			const next = previous.length === fileColumns.length
				? [...previous]
				: Array.from({ length: fileColumns.length }, () => true);
			next[index] = !next[index];
			return next;
		});
	}, [fileColumns.length]);

	const handleSelectAllColumns = useCallback(
		(select: boolean): void => {
			setFileKeep(Array.from({ length: fileColumns.length }, () => select));
		},
		[fileColumns.length],
	);

	/** The connection payload for the API endpoints (form text → JSON). */
	const buildApiConnection = useCallback((): Record<string, unknown> => {
		const columns =
			apiPreview == null
				? []
				: apiPreview.columns.map((column, index) => ({
						source: column.source,
						name: (apiColumns[index] ?? column.name).trim() || column.name,
					}));
		return {
			type: 'api',
			database: apiValues.database.trim(),
			url: apiValues.url.trim(),
			method: apiValues.method,
			headers: apiValues.headers,
			params: apiValues.params,
			body: apiValues.method === 'POST' ? apiValues.body : '',
			records_path: apiValues.recordsPath.trim(),
			auth_type: apiValues.authType,
			token: apiValues.token,
			user: apiValues.authType === 'basic' ? apiValues.user.trim() : '',
			password: apiValues.authType === 'basic' ? apiValues.password : '',
			timeout_s: Number.parseInt(apiValues.timeout, 10) || 30,
			columns,
		};
	}, [apiColumns, apiPreview, apiValues]);

	const handleLoadApi = useCallback(async (): Promise<void> => {
		setApiBusy(true);
		setApiError(null);
		setAlert(null);
		const res = await connectionsApi.previewApi(
			buildApiConnection(),
			editing ? connection?.database_name : undefined,
		);
		setApiBusy(false);

		if ('error' in res && res.error) {
			setApiPreview(null);
			setApiColumns([]);
			setApiError(res.message ?? t('Could not read the API.'));
			return;
		}
		setApiPreview(res);
		setApiColumns(res.columns.map((column) => column.name));
		setApiFetchedAt(new Date().toISOString());
	}, [buildApiConnection, connection, editing]);

	const handleApiColumnNameChange = useCallback((index: number, name: string): void => {
		setApiColumns((previous) =>
			previous.map((value, position) => (position === index ? name : value)),
		);
	}, []);

	const handleTestConnection = useCallback(async (): Promise<void> => {
		setTestingConnection(true);
		setAlert(null);
		setTestSuccessMessage(null);

		const res = await connectionsApi.test(
			buildConnection({ forTest: true }),
			connection?.database_name,
		);
		setTestingConnection(false);

		if ('error' in res && res.error) {
			setIsConnectionTested(false);
			setAlert(res.message ?? t('Connection test failed.'));
			return;
		}

		if (!('success' in res)) {
			setIsConnectionTested(false);
			setAlert(t('Connection test failed.'));
			return;
		}

		setIsConnectionTested(true);
		setTestSuccessMessage(t('Connection successful.'));
		// The test response carries the connection's schemas — feed the picker.
		setAvailableSchemas(res.schemas);
		setAlert(null);
	}, [buildConnection, connection]);

	const handleSubmit = useCallback(async (): Promise<void> => {
		if (isApiType) {
			if (apiPreview == null) {
				setAlert(t('Load the data before saving.'));
				return;
			}
			if (apiValues.database.trim() === '') {
				setAlert(t('A name is required.'));
				return;
			}
			const apiNameProblem = connectionNameProblem(apiValues.database);
			if (apiNameProblem) {
				setAlert(apiNameProblem);
				return;
			}

			setLoading(true);
			setAlert(null);
			const payload = buildApiConnection();
			const res =
				editing && connection != null
					? await connectionsApi.updateApi(connection.database_name, payload)
					: await connectionsApi.createApi(payload);
			setLoading(false);

			if ('error' in res && res.error) {
				const message =
					'message' in res && typeof res.message === 'string' ? res.message : undefined;
				setAlert(
					message ??
						(editing
							? t('Failed to update the connection.')
							: t('Failed to create the connection.')),
				);
				return;
			}
			onConfirm();
			return;
		}

		if (isFileType) {
			const hasSource =
				fileSourceMode === 'server' ? serverPath.trim() !== '' : selectedFile != null;
			if (!hasSource || filePreview == null) {
				setAlert(
					fileSourceMode === 'server'
						? t('Choose a server file and load it before saving.')
						: t('Choose a file and wait for it to load before saving.'),
				);
				return;
			}
			if (fileDatabase.trim() === '') {
				setAlert(t('A name is required.'));
				return;
			}
			const fileNameProblem = connectionNameProblem(fileDatabase);
			if (fileNameProblem) {
				setAlert(fileNameProblem);
				return;
			}

			setLoading(true);
			setAlert(null);
			const keepColumns = (
				fileKeep.length === fileColumns.length
					? fileKeep
					: Array.from({ length: fileColumns.length }, () => true)
			)
				.map((selected, index) => (selected ? index : -1))
				.filter((index) => index >= 0);
			if (keepColumns.length === 0) {
				setLoading(false);
				setAlert(t('Select at least one column.'));
				return;
			}
			const fileSettings = {
				sheet: fileSheet,
				delimiter: effectiveDelimiter || null,
				header_row: fileHeaderRow,
				columns: fileColumns,
				keep_columns: keepColumns,
			};
			let res: { data: Connection } | { error: boolean; message?: string };
			if (fileSourceMode === 'server') {
				res =
					editing && connection != null
						? await connectionsApi.replaceServerFile(connection.database_name, {
								path: serverPath.trim(),
								...fileSettings,
							})
						: await connectionsApi.createServerFile({
								path: serverPath.trim(),
								database: fileDatabase.trim(),
								...fileSettings,
							});
			} else {
				if (selectedFile == null) {
					setLoading(false);
					setAlert(t('Choose a file before saving.'));
					return;
				}
				res =
					editing && connection != null
						? await connectionsApi.replaceFile(
								connection.database_name,
								selectedFile,
								fileSettings,
							)
						: await connectionsApi.createFile(selectedFile, {
								database: fileDatabase.trim(),
								...fileSettings,
							});
			}
			setLoading(false);

			if ('error' in res && res.error) {
				const message =
					'message' in res && typeof res.message === 'string' ? res.message : undefined;
				setAlert(
						message ??
							(editing
								? t('Failed to update the connection.')
								: t('Failed to create the connection.')),
				);
				return;
			}
			onConfirm();
			return;
		}

		if (!isConnectionTested) {
			setAlert(
				editing
					? t('Connection must be tested before saving.')
					: t('Connection must be tested before creating.'),
			);
			return;
		}

		const input = buildConnection();
		if (connection == null) {
			const sqlNameProblem = connectionNameProblem(
				String((input as Record<string, unknown>).database ?? ''),
			);
			if (sqlNameProblem) {
				setAlert(sqlNameProblem);
				return;
			}
		}
		setLoading(true);
		setAlert(null);
		const res =
			connection == null
				? await connectionsApi.create(input)
				: await connectionsApi.update(connection.database_name, input);
		setLoading(false);

		if ('error' in res && res.error) {
			setAlert(
				res.message ??
					(editing
						? t('Failed to update the connection.')
						: t('Failed to create the connection.')),
			);
			return;
		}

		onConfirm();
	}, [
		apiPreview,
		apiValues.database,
		buildConnection,
		buildApiConnection,
		connection,
		editing,
		fileColumns,
		fileDatabase,
		effectiveDelimiter,
		fileHeaderRow,
		fileKeep,
		filePreview,
		fileSheet,
		fileSourceMode,
		isConnectionTested,
		isApiType,
		isFileType,
		onConfirm,
		selectedFile,
		serverPath,
	]);

	const renderStepContent = (step: number) => {
		switch (steps[step]) {
			case TYPE_STEP:
				return <ConnectionTypeStep onSelect={handleSelectType} />;
			case FILE_STEP:
				return (
					<FileConnectionStep
						databaseName={fileDatabase}
						onDatabaseNameChange={setFileDatabase}
						nameReadOnly={editing}
						existingFileName={editing ? (storedFile?.filename ?? null) : null}
						sourceMode={fileSourceMode}
						onSourceModeChange={handleFileSourceModeChange}
						serverPath={serverPath}
						onServerPathChange={handleServerPathChange}
						onLoadServerPath={handleLoadServerPath}
						onBrowseServerPaths={handleBrowseServerPaths}
						selectedFileName={selectedFile?.name ?? null}
						preview={filePreview}
						busy={fileBusy}
						error={fileError}
						sheet={fileSheet}
						delimiter={fileDelimiter}
						customDelimiter={customDelimiter}
						headerRow={fileHeaderRow}
						columnNames={fileColumns}
						selectedColumns={fileKeep}
						onSelectFile={handleSelectFile}
						onSheetChange={handleSheetChange}
						onDelimiterChange={handleDelimiterChange}
						onCustomDelimiterChange={handleCustomDelimiterChange}
						onHeaderRowChange={handleHeaderRowChange}
						onColumnNameChange={handleColumnNameChange}
						onColumnToggle={handleColumnToggle}
						onSelectAllColumns={handleSelectAllColumns}
					/>
				);
			case API_STEP:
				return (
					<ApiConnectionStep
						values={apiValues}
						onFieldChange={(key, value) =>
							setApiValues((previous) => ({ ...previous, [key]: value }))
						}
						nameReadOnly={editing}
						preview={apiPreview}
						columnNames={apiColumns}
						onColumnNameChange={handleApiColumnNameChange}
						onLoad={() => {
							void handleLoadApi();
						}}
						busy={apiBusy}
						error={apiError}
						fetchedAt={apiFetchedAt}
					/>
				);
			case CONNECT_STEP:
				return (
					<ConnectionConnectStep
						connectionType={connectionType}
						values={values}
						onFieldChange={handleFieldChange}
						readOnlyKeys={readOnlyKeys}
						keepCurrentKeys={keepCurrentKeys}
						testSuccessMessage={testSuccessMessage}
						onTestConnection={() => {
							void handleTestConnection();
						}}
						testDisabled={!fieldsComplete || loading}
						testingConnection={testingConnection}
					/>
				);
			case SCHEMA_STEP:
				return (
					<div className="flex flex-col gap-2">
						<p className="px-2 text-xs text-secondary dark:text-zinc-400">
							{t('Leave empty to ingest all schemas.')}{' '}
						</p>
						<ConnectionSelectDataStep
							availableDatabases={availableSchemas}
							selectedDatabases={selectedSchemas}
							onSelectionChange={setSelectedSchemas}
						/>
					</div>
				);
			default:
				return null;
		}
	};

	const footerActions: StepperFooterAction[] = useMemo(() => {
		if (onTypeStep) {
			return [{ label: t('Cancel'), onClick: onCancel, variant: 'outline' }];
		}

		const actions: StepperFooterAction[] = [
			activeStep === 0
				? { label: t('Cancel'), onClick: onCancel, variant: 'outline' }
				: { label: t('Back'), onClick: handleBack, variant: 'outline' },
		];

		const isLastStep = activeStep === steps.length - 1;
		// Require a successful test before advancing so the schema list can load.
		const fileHasSource =
			fileSourceMode === 'server' ? serverPath.trim() !== '' : selectedFile != null;
		// Deliberately does not include the name: an empty or invalid name is
		// reported on submit with a specific message instead of leaving the
		// operator with a disabled button and no visible reason.
		const fileReady = fileHasSource && filePreview != null;
		const apiReady =
			apiPreview != null &&
			apiValues.database.trim() !== '' &&
			(editing || isValidConnectionName(apiValues.database));
		const blocked = isFileType
			? loading || fileBusy || !fileReady
			: isApiType
				? loading || apiBusy || !apiReady
				: !canContinue || loading || testingConnection || !isConnectionTested;

		actions.push(
			isLastStep
				? {
						label: editing ? t('Save') : t('Create'),
						onClick: () => {
							void handleSubmit();
						},
						disabled: blocked,
						loading,
					}
				: { label: t('Next'), onClick: handleNext, disabled: blocked, loading },
		);

		return actions;
	}, [
		activeStep,
		apiBusy,
		apiPreview,
		apiValues.database,
		canContinue,
		editing,
		fileBusy,
		filePreview,
		fileSourceMode,
		handleBack,
		handleNext,
		handleSubmit,
		isConnectionTested,
		isApiType,
		isFileType,
		loading,
		onCancel,
		onTypeStep,
		selectedFile,
		serverPath,
		steps.length,
		testingConnection,
	]);

	return (
		<ModalWithSteps
			open={open}
			onClose={onCancel}
			title={
				editing
					? t('Edit {0}', { 0: connection.database_name })
					: t('Create New Connection')
			}
			steps={steps.map((step) => t(step))}
			activeStep={activeStep}
			onActiveStepChange={setActiveStep}
			footerActions={footerActions}
			alert={alert}
		>
			{renderStepContent(activeStep)}
		</ModalWithSteps>
	);
};
