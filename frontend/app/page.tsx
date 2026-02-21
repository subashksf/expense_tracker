"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { SignInButton, SignUpButton, SignedIn, SignedOut, UserButton, useAuth } from "@clerk/nextjs";
import {
  createCategory,
  createClassificationRule,
  createManualTransaction,
  deleteClassificationRule,
  fetchDuplicateReviews,
  fetchInsight,
  fetchCategories,
  fetchClassificationRules,
  fetchImport,
  loadClassificationRulesConfig,
  recategorizeTransactions,
  resolveDuplicateReview,
  resolveDuplicateReviewsBulk,
  saveClassificationRulesConfig,
  setApiAccessTokenProvider,
  fetchTransactions,
  generateInsights,
  updateClassificationRule,
  updateTransactionCategory,
  uploadStatement
} from "../lib/api";
import type {
  ClassificationRule,
  ClassificationRuleType,
  DuplicateReview,
  InsightReport,
  StatementImport,
  Transaction
} from "../lib/types";

const NEW_CATEGORY_OPTION = "__new__";
type SaveStatus = "idle" | "saving" | "saved" | "error";
type TabId = "transactions" | "insights" | "rules";
type RuleDraft = {
  rule_type: ClassificationRuleType;
  pattern: string;
  category: string;
  confidence: string;
  priority: string;
  is_active: boolean;
};

const RULE_TYPES: ClassificationRuleType[] = [
  "source_category_contains",
  "merchant_exact",
  "merchant_contains",
  "description_contains",
  "text_contains"
];

function toRuleDraft(rule: ClassificationRule): RuleDraft {
  return {
    rule_type: rule.rule_type,
    pattern: rule.pattern,
    category: rule.category,
    confidence: String(rule.confidence),
    priority: String(rule.priority),
    is_active: rule.is_active
  };
}

export default function HomePage() {
  const { getToken, isLoaded, isSignedIn } = useAuth();
  const [activeTab, setActiveTab] = useState<TabId>("transactions");
  const [file, setFile] = useState<File | null>(null);
  const [importInfo, setImportInfo] = useState<StatementImport | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string>("");

  const [categories, setCategories] = useState<string[]>([]);
  const [loadingCategories, setLoadingCategories] = useState(false);
  const [categoryError, setCategoryError] = useState("");

  const [classificationRules, setClassificationRules] = useState<ClassificationRule[]>([]);
  const [ruleDrafts, setRuleDrafts] = useState<Record<string, RuleDraft>>({});
  const [loadingRules, setLoadingRules] = useState(false);
  const [ruleError, setRuleError] = useState("");
  const [ruleSaveState, setRuleSaveState] = useState<Record<string, SaveStatus>>({});
  const [creatingRule, setCreatingRule] = useState(false);
  const [deletingRuleId, setDeletingRuleId] = useState("");
  const [newRuleType, setNewRuleType] = useState<ClassificationRuleType>("merchant_contains");
  const [newRulePattern, setNewRulePattern] = useState("");
  const [newRuleCategory, setNewRuleCategory] = useState("");
  const [newRuleConfidence, setNewRuleConfidence] = useState("0.9");
  const [newRulePriority, setNewRulePriority] = useState("20");
  const [newRuleActive, setNewRuleActive] = useState(true);
  const [rulesConfigSyncing, setRulesConfigSyncing] = useState(false);
  const [rulesConfigMessage, setRulesConfigMessage] = useState("");

  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [loadingTransactions, setLoadingTransactions] = useState(false);
  const [txError, setTxError] = useState("");
  const [recategorizing, setRecategorizing] = useState(false);
  const [recategorizeMessage, setRecategorizeMessage] = useState("");
  const [duplicateReviews, setDuplicateReviews] = useState<DuplicateReview[]>([]);
  const [loadingDuplicateReviews, setLoadingDuplicateReviews] = useState(false);
  const [duplicateReviewError, setDuplicateReviewError] = useState("");
  const [duplicateReviewMessage, setDuplicateReviewMessage] = useState("");
  const [duplicateReviewActionState, setDuplicateReviewActionState] = useState<Record<string, SaveStatus>>({});
  const [duplicateBulkResolvingAction, setDuplicateBulkResolvingAction] = useState<"mark_duplicate" | "not_duplicate" | null>(null);
  const [transactionReviewExpanded, setTransactionReviewExpanded] = useState(false);
  const [uncategorizedReviewExpanded, setUncategorizedReviewExpanded] = useState(false);
  const [duplicateReviewExpanded, setDuplicateReviewExpanded] = useState(false);

  const [uncategorizedRows, setUncategorizedRows] = useState<Transaction[]>([]);
  const [loadingUncategorized, setLoadingUncategorized] = useState(false);
  const [uncategorizedError, setUncategorizedError] = useState("");

  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [category, setCategory] = useState("");

  const [editDrafts, setEditDrafts] = useState<Record<string, string>>({});
  const [saveState, setSaveState] = useState<Record<string, SaveStatus>>({});
  const [uncategorizedSelection, setUncategorizedSelection] = useState<Record<string, string>>(
    {}
  );
  const [newCategoryInputs, setNewCategoryInputs] = useState<Record<string, string>>({});
  const [uncategorizedSaveState, setUncategorizedSaveState] = useState<Record<string, SaveStatus>>({});
  const [uncategorizedRowError, setUncategorizedRowError] = useState<Record<string, string>>({});

  const [insightStartDate, setInsightStartDate] = useState("");
  const [insightEndDate, setInsightEndDate] = useState("");
  const [insightId, setInsightId] = useState("");
  const [insightReport, setInsightReport] = useState<InsightReport | null>(null);
  const [generatingInsight, setGeneratingInsight] = useState(false);
  const [loadingInsight, setLoadingInsight] = useState(false);
  const [insightError, setInsightError] = useState("");

  const [manualDate, setManualDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [manualDescription, setManualDescription] = useState("");
  const [manualMerchant, setManualMerchant] = useState("");
  const [manualAmount, setManualAmount] = useState("");
  const [manualCategory, setManualCategory] = useState("");
  const [manualNewCategory, setManualNewCategory] = useState("");
  const [manualSaving, setManualSaving] = useState(false);
  const [manualError, setManualError] = useState("");
  const [manualSuccess, setManualSuccess] = useState("");

  const query = useMemo(
    () => ({
      start_date: startDate || undefined,
      end_date: endDate || undefined,
      category: category || undefined,
      limit: 200,
      offset: 0
    }),
    [startDate, endDate, category]
  );

  const assignableCategories = useMemo(
    () => categories.filter((item) => item !== "uncategorized"),
    [categories]
  );

  const refreshCategories = useCallback(async () => {
    setLoadingCategories(true);
    setCategoryError("");
    try {
      const rows = await fetchCategories();
      const names = rows.map((row) => row.name);
      setCategories(names.includes("uncategorized") ? names : [...names, "uncategorized"]);
    } catch (error) {
      setCategoryError(error instanceof Error ? error.message : "Failed to load categories.");
    } finally {
      setLoadingCategories(false);
    }
  }, []);

  const refreshClassificationRules = useCallback(async () => {
    setLoadingRules(true);
    setRuleError("");
    try {
      const rows = await fetchClassificationRules();
      setClassificationRules(rows);
      setRuleDrafts(
        rows.reduce<Record<string, RuleDraft>>((acc, row) => {
          acc[row.id] = toRuleDraft(row);
          return acc;
        }, {})
      );
    } catch (error) {
      setRuleError(error instanceof Error ? error.message : "Failed to load classification rules.");
    } finally {
      setLoadingRules(false);
    }
  }, []);

  const refreshTransactions = useCallback(async () => {
    setLoadingTransactions(true);
    setTxError("");
    try {
      const rows = await fetchTransactions(query);
      setTransactions(rows);
      setEditDrafts(
        rows.reduce<Record<string, string>>((acc, row) => {
          acc[row.id] = row.category;
          return acc;
        }, {})
      );
    } catch (error) {
      setTxError(error instanceof Error ? error.message : "Failed to load transactions.");
    } finally {
      setLoadingTransactions(false);
    }
  }, [query]);

  const refreshUncategorized = useCallback(async () => {
    setLoadingUncategorized(true);
    setUncategorizedError("");
    try {
      const rows = await fetchTransactions({
        category: "uncategorized",
        limit: 500,
        offset: 0
      });
      setUncategorizedRows(rows);
      const defaultCategory = assignableCategories[0] ?? NEW_CATEGORY_OPTION;
      setUncategorizedSelection((prev) =>
        rows.reduce<Record<string, string>>((acc, row) => {
          acc[row.id] = prev[row.id] ?? defaultCategory;
          return acc;
        }, {})
      );
    } catch (error) {
      setUncategorizedError(error instanceof Error ? error.message : "Failed to load uncategorized transactions.");
    } finally {
      setLoadingUncategorized(false);
    }
  }, [assignableCategories]);

  const refreshDuplicateReviews = useCallback(async () => {
    setLoadingDuplicateReviews(true);
    setDuplicateReviewError("");
    setDuplicateReviewMessage("");
    try {
      const rows = await fetchDuplicateReviews({
        status: "pending",
        limit: 500,
        offset: 0
      });
      setDuplicateReviews(rows);
    } catch (error) {
      setDuplicateReviewError(error instanceof Error ? error.message : "Failed to load duplicate review queue.");
    } finally {
      setLoadingDuplicateReviews(false);
    }
  }, []);

  async function handleUpload() {
    if (!file) {
      setUploadError("Choose a CSV file first.");
      return;
    }
    setUploading(true);
    setUploadError("");
    try {
      const info = await uploadStatement(file);
      setImportInfo(info);
      setFile(null);
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : "Upload failed.");
    } finally {
      setUploading(false);
    }
  }

  async function saveCategory(transactionId: string) {
    const nextCategory = editDrafts[transactionId];
    if (!nextCategory) return;
    setSaveState((prev) => ({ ...prev, [transactionId]: "saving" }));
    try {
      const updated = await updateTransactionCategory(transactionId, nextCategory);
      setTransactions((prev) => prev.map((tx) => (tx.id === transactionId ? updated : tx)));
      setSaveState((prev) => ({ ...prev, [transactionId]: "saved" }));
      setTimeout(() => {
        setSaveState((prev) => ({ ...prev, [transactionId]: "idle" }));
      }, 1200);
    } catch {
      setSaveState((prev) => ({ ...prev, [transactionId]: "error" }));
    }
  }

  async function handleRecategorizeTransactions() {
    setTxError("");
    setRecategorizeMessage("");
    setRecategorizing(true);
    try {
      const result = await recategorizeTransactions({
        start_date: startDate || undefined,
        end_date: endDate || undefined,
        category: category || undefined,
        include_user_assigned: false
      });
      setRecategorizeMessage(
        `Re-categorized ${result.updated_rows} of ${result.scanned_rows} scanned transactions (${result.skipped_user_assigned_rows} user-assigned skipped).`
      );
      await refreshTransactions();
      await refreshUncategorized();
    } catch (error) {
      setTxError(error instanceof Error ? error.message : "Failed to recategorize transactions.");
    } finally {
      setRecategorizing(false);
    }
  }

  async function applyUncategorizedCategory(transactionId: string) {
    const selected = uncategorizedSelection[transactionId];
    if (!selected) {
      return;
    }

    setUncategorizedSaveState((prev) => ({ ...prev, [transactionId]: "saving" }));
    setUncategorizedRowError((prev) => ({ ...prev, [transactionId]: "" }));

    try {
      let targetCategory = selected;
      if (selected === NEW_CATEGORY_OPTION) {
        const proposed = (newCategoryInputs[transactionId] || "").trim();
        if (!proposed) {
          throw new Error("Enter a new category name first.");
        }
        const created = await createCategory(proposed);
        targetCategory = created.name;
        setCategories((prev) => {
          if (prev.includes(created.name)) {
            return prev;
          }
          return [...prev, created.name].sort();
        });
        setUncategorizedSelection((prev) => ({
          ...prev,
          [transactionId]: created.name
        }));
      }

      const updated = await updateTransactionCategory(transactionId, targetCategory);

      setTransactions((prev) => {
        if (category === "uncategorized") {
          return prev.filter((tx) => tx.id !== transactionId);
        }
        return prev.map((tx) => (tx.id === transactionId ? updated : tx));
      });

      setUncategorizedRows((prev) => prev.filter((tx) => tx.id !== transactionId));
      setUncategorizedSaveState((prev) => ({ ...prev, [transactionId]: "saved" }));
      setTimeout(() => {
        setUncategorizedSaveState((prev) => ({ ...prev, [transactionId]: "idle" }));
      }, 1200);
    } catch (error) {
      setUncategorizedSaveState((prev) => ({ ...prev, [transactionId]: "error" }));
      setUncategorizedRowError((prev) => ({
        ...prev,
        [transactionId]: error instanceof Error ? error.message : "Failed to update category."
      }));
    }
  }

  async function handleCreateRule() {
    setRuleError("");
    const pattern = newRulePattern.trim();
    const categoryValue = newRuleCategory.trim();
    const confidence = Number(newRuleConfidence);
    const priority = Number(newRulePriority);

    if (!pattern) {
      setRuleError("Rule pattern is required.");
      return;
    }
    if (!categoryValue) {
      setRuleError("Rule category is required.");
      return;
    }
    if (!Number.isFinite(confidence) || confidence < 0 || confidence > 1) {
      setRuleError("Rule confidence must be between 0 and 1.");
      return;
    }
    if (!Number.isInteger(priority) || priority < 0) {
      setRuleError("Rule priority must be a non-negative integer.");
      return;
    }

    setCreatingRule(true);
    try {
      await createClassificationRule({
        rule_type: newRuleType,
        pattern,
        category: categoryValue,
        confidence,
        priority,
        is_active: newRuleActive
      });
      setNewRulePattern("");
      await refreshCategories();
      await refreshClassificationRules();
    } catch (error) {
      setRuleError(error instanceof Error ? error.message : "Failed to create classification rule.");
    } finally {
      setCreatingRule(false);
    }
  }

  async function handleSaveRule(ruleId: string) {
    const draft = ruleDrafts[ruleId];
    if (!draft) {
      return;
    }

    const pattern = draft.pattern.trim();
    const categoryValue = draft.category.trim();
    const confidence = Number(draft.confidence);
    const priority = Number(draft.priority);

    if (!pattern) {
      setRuleError("Rule pattern is required.");
      return;
    }
    if (!categoryValue) {
      setRuleError("Rule category is required.");
      return;
    }
    if (!Number.isFinite(confidence) || confidence < 0 || confidence > 1) {
      setRuleError("Rule confidence must be between 0 and 1.");
      return;
    }
    if (!Number.isInteger(priority) || priority < 0) {
      setRuleError("Rule priority must be a non-negative integer.");
      return;
    }

    setRuleError("");
    setRuleSaveState((prev) => ({ ...prev, [ruleId]: "saving" }));
    try {
      const updated = await updateClassificationRule(ruleId, {
        rule_type: draft.rule_type,
        pattern,
        category: categoryValue,
        confidence,
        priority,
        is_active: draft.is_active
      });
      setClassificationRules((prev) => prev.map((item) => (item.id === ruleId ? updated : item)));
      setRuleDrafts((prev) => ({ ...prev, [ruleId]: toRuleDraft(updated) }));
      setRuleSaveState((prev) => ({ ...prev, [ruleId]: "saved" }));
      setTimeout(() => {
        setRuleSaveState((prev) => ({ ...prev, [ruleId]: "idle" }));
      }, 1200);
      await refreshCategories();
    } catch (error) {
      setRuleSaveState((prev) => ({ ...prev, [ruleId]: "error" }));
      setRuleError(error instanceof Error ? error.message : "Failed to update classification rule.");
    }
  }

  async function handleDeleteRule(ruleId: string) {
    setRuleError("");
    setDeletingRuleId(ruleId);
    try {
      await deleteClassificationRule(ruleId);
      setClassificationRules((prev) => prev.filter((item) => item.id !== ruleId));
      setRuleDrafts((prev) => {
        const next = { ...prev };
        delete next[ruleId];
        return next;
      });
      setRuleSaveState((prev) => {
        const next = { ...prev };
        delete next[ruleId];
        return next;
      });
    } catch (error) {
      setRuleError(error instanceof Error ? error.message : "Failed to delete classification rule.");
    } finally {
      setDeletingRuleId("");
    }
  }

  async function handleSaveRulesToConfig() {
    setRuleError("");
    setRulesConfigMessage("");
    setRulesConfigSyncing(true);
    try {
      const result = await saveClassificationRulesConfig();
      setRulesConfigMessage(`Saved ${result.exported_rules} rules to ${result.path}.`);
    } catch (error) {
      setRuleError(error instanceof Error ? error.message : "Failed to save rules to config file.");
    } finally {
      setRulesConfigSyncing(false);
    }
  }

  async function handleLoadRulesFromConfig() {
    setRuleError("");
    setRulesConfigMessage("");
    setRulesConfigSyncing(true);
    try {
      const result = await loadClassificationRulesConfig(true);
      setRulesConfigMessage(`Loaded ${result.loaded_rules} rules from ${result.path}.`);
      await refreshCategories();
      await refreshClassificationRules();
    } catch (error) {
      setRuleError(error instanceof Error ? error.message : "Failed to load rules from config file.");
    } finally {
      setRulesConfigSyncing(false);
    }
  }

  async function handleResolveDuplicateReview(reviewId: string, action: "mark_duplicate" | "not_duplicate") {
    setDuplicateReviewError("");
    setDuplicateReviewMessage("");
    setDuplicateReviewActionState((prev) => ({ ...prev, [reviewId]: "saving" }));
    try {
      const result = await resolveDuplicateReview(reviewId, action);
      setDuplicateReviews((prev) => prev.filter((row) => row.id !== reviewId));
      if (result.created_transaction_id) {
        setDuplicateReviewMessage(`Not Duplicate applied: transaction ${result.created_transaction_id} created.`);
        await refreshTransactions();
        await refreshUncategorized();
      } else {
        setDuplicateReviewMessage("Marked as duplicate and removed from queue.");
      }
      setDuplicateReviewActionState((prev) => ({ ...prev, [reviewId]: "saved" }));
      setTimeout(() => {
        setDuplicateReviewActionState((prev) => ({ ...prev, [reviewId]: "idle" }));
      }, 800);
    } catch (error) {
      setDuplicateReviewActionState((prev) => ({ ...prev, [reviewId]: "error" }));
      setDuplicateReviewError(error instanceof Error ? error.message : "Failed to update duplicate review status.");
    }
  }

  async function handleBulkResolveDuplicateReviews(action: "mark_duplicate" | "not_duplicate") {
    setDuplicateReviewError("");
    setDuplicateReviewMessage("");

    const reviewIds = duplicateReviews.map((row) => row.id);
    if (reviewIds.length === 0) {
      setDuplicateReviewMessage("No duplicate reviews are currently shown.");
      return;
    }

    const actionLabel = action === "mark_duplicate" ? "mark all shown as duplicate" : "approve all shown as not duplicate";
    const confirmed = window.confirm(
      `This will ${actionLabel} for ${reviewIds.length} rows currently shown. Continue?`
    );
    if (!confirmed) {
      return;
    }

    setDuplicateBulkResolvingAction(action);
    try {
      const result = await resolveDuplicateReviewsBulk(reviewIds, action);
      setDuplicateReviewMessage(
        `Bulk action complete. Processed ${result.processed_count}/${result.requested_count}; created ${result.created_transactions_count} transactions; skipped missing ${result.skipped_missing_count}, non-pending ${result.skipped_non_pending_count}.`
      );
      await refreshDuplicateReviews();
      if (result.created_transactions_count > 0) {
        await refreshTransactions();
        await refreshUncategorized();
      }
    } catch (error) {
      setDuplicateReviewError(error instanceof Error ? error.message : "Failed to run bulk duplicate review action.");
    } finally {
      setDuplicateBulkResolvingAction(null);
    }
  }

  async function handleGenerateInsights() {
    setGeneratingInsight(true);
    setInsightError("");
    try {
      const report = await generateInsights({
        start_date: insightStartDate || undefined,
        end_date: insightEndDate || undefined
      });
      setInsightReport(report);
      setInsightId(report.id);
    } catch (error) {
      setInsightError(error instanceof Error ? error.message : "Failed to generate insights.");
    } finally {
      setGeneratingInsight(false);
    }
  }

  async function handleLoadInsight() {
    if (!insightId.trim()) {
      setInsightError("Enter an insight id.");
      return;
    }
    setLoadingInsight(true);
    setInsightError("");
    try {
      const report = await fetchInsight(insightId.trim());
      setInsightReport(report);
    } catch (error) {
      setInsightError(error instanceof Error ? error.message : "Failed to load insight report.");
    } finally {
      setLoadingInsight(false);
    }
  }

  async function handleAddManualExpense() {
    setManualError("");
    setManualSuccess("");
    if (!manualDate) {
      setManualError("Select a date.");
      return;
    }
    if (!manualDescription.trim()) {
      setManualError("Description is required.");
      return;
    }
    const parsedAmount = Number(manualAmount);
    if (!Number.isFinite(parsedAmount) || parsedAmount <= 0) {
      setManualError("Amount must be a positive number.");
      return;
    }

    setManualSaving(true);
    try {
      let finalCategory = manualCategory || assignableCategories[0] || "uncategorized";
      if (finalCategory === NEW_CATEGORY_OPTION) {
        const proposed = manualNewCategory.trim();
        if (!proposed) {
          throw new Error("Enter a new category name.");
        }
        const created = await createCategory(proposed);
        finalCategory = created.name;
        setCategories((prev) => {
          if (prev.includes(created.name)) {
            return prev;
          }
          return [...prev, created.name].sort();
        });
        setManualCategory(created.name);
        setManualNewCategory("");
      }

      await createManualTransaction({
        transaction_date: manualDate,
        description_raw: manualDescription.trim(),
        merchant_normalized: manualMerchant.trim() || undefined,
        amount: parsedAmount,
        currency: "USD",
        direction: "debit",
        category: finalCategory
      });

      setManualDescription("");
      setManualMerchant("");
      setManualAmount("");
      setManualSuccess("Expense saved.");
      refreshTransactions();
      refreshUncategorized();
    } catch (error) {
      setManualError(error instanceof Error ? error.message : "Failed to save manual expense.");
    } finally {
      setManualSaving(false);
    }
  }

  useEffect(() => {
    setApiAccessTokenProvider(async () => {
      if (!isLoaded || !isSignedIn) {
        return null;
      }
      return (await getToken()) ?? null;
    });
    return () => setApiAccessTokenProvider(null);
  }, [getToken, isLoaded, isSignedIn]);

  useEffect(() => {
    if (!isLoaded || !isSignedIn) {
      setImportInfo(null);
      setTransactions([]);
      setUncategorizedRows([]);
      setDuplicateReviews([]);
      return;
    }
    refreshCategories();
  }, [isLoaded, isSignedIn, refreshCategories]);

  useEffect(() => {
    if (!isLoaded || !isSignedIn) return;
    refreshClassificationRules();
  }, [isLoaded, isSignedIn, refreshClassificationRules]);

  useEffect(() => {
    if (!manualCategory && assignableCategories.length > 0) {
      setManualCategory(assignableCategories[0]);
    }
  }, [assignableCategories, manualCategory]);

  useEffect(() => {
    if (!newRuleCategory && assignableCategories.length > 0) {
      setNewRuleCategory(assignableCategories[0]);
    }
  }, [assignableCategories, newRuleCategory]);

  useEffect(() => {
    if (!isLoaded || !isSignedIn) return;
    refreshTransactions();
  }, [isLoaded, isSignedIn, refreshTransactions]);

  useEffect(() => {
    if (!isLoaded || !isSignedIn) return;
    refreshUncategorized();
  }, [isLoaded, isSignedIn, refreshUncategorized]);

  useEffect(() => {
    if (!isLoaded || !isSignedIn) return;
    refreshDuplicateReviews();
  }, [isLoaded, isSignedIn, refreshDuplicateReviews]);

  useEffect(() => {
    if (!isLoaded || !isSignedIn) return;
    if (!importInfo) return;
    if (importInfo.status === "completed" || importInfo.status === "failed") return;

    const interval = setInterval(async () => {
      try {
        const updated = await fetchImport(importInfo.id);
        setImportInfo(updated);
        if (updated.status === "completed") {
          refreshTransactions();
          refreshUncategorized();
          refreshDuplicateReviews();
        }
      } catch {
        // best-effort polling
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [isLoaded, isSignedIn, importInfo, refreshDuplicateReviews, refreshTransactions, refreshUncategorized]);

  return (
    <>
    <SignedOut>
      <main className="page">
        <div className="bg-shape bg-shape-left" />
        <div className="bg-shape bg-shape-right" />
        <section className="hero">
          <h1>Expense Tracker</h1>
          <p>Sign in to upload statements, review categories, and generate insights.</p>
          <div className="insight-actions">
            <SignInButton mode="modal">
              <button type="button">Sign In</button>
            </SignInButton>
            <SignUpButton mode="modal">
              <button type="button">Sign Up</button>
            </SignUpButton>
          </div>
        </section>
      </main>
    </SignedOut>
    <SignedIn>
    <main className="page">
      <div className="bg-shape bg-shape-left" />
      <div className="bg-shape bg-shape-right" />

      <section className="hero">
        <div className="card-head">
          <h1>Expense Tracker</h1>
          <UserButton afterSignOutUrl="/" />
        </div>
        <p>Upload statements, review categories, and keep your spend data clean for AI insights.</p>
      </section>

      <section className="tabs" aria-label="Primary sections">
        <button
          type="button"
          className={`tab-button${activeTab === "transactions" ? " tab-button-active" : ""}`}
          onClick={() => setActiveTab("transactions")}
        >
          Transactions
        </button>
        <button
          type="button"
          className={`tab-button${activeTab === "insights" ? " tab-button-active" : ""}`}
          onClick={() => setActiveTab("insights")}
        >
          Insights
        </button>
        <button
          type="button"
          className={`tab-button${activeTab === "rules" ? " tab-button-active" : ""}`}
          onClick={() => setActiveTab("rules")}
        >
          Rules
        </button>
      </section>

      {activeTab === "transactions" ? (
      <section className="card upload-card">
        <div className="card-head">
          <h2>Upload Statement</h2>
          <span className="pill">CSV only</span>
        </div>
        <div className="upload-controls">
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
          <button type="button" onClick={handleUpload} disabled={uploading}>
            {uploading ? "Uploading..." : "Upload and Process"}
          </button>
        </div>
        {uploadError ? <p className="error">{uploadError}</p> : null}
        {importInfo ? (
          <div className="import-status">
            <p>
              <strong>File:</strong> {importInfo.filename}
            </p>
            <p>
              <strong>Status:</strong> <span className={`status status-${importInfo.status}`}>{importInfo.status}</span>
            </p>
            <p>
              <strong>Processed:</strong> {importInfo.processed_rows} / {importInfo.total_rows}
            </p>
            {importInfo.error_message ? <p className="error">{importInfo.error_message}</p> : null}
          </div>
        ) : null}
      </section>
      ) : null}

      {activeTab === "transactions" ? (
      <section className="card">
        <div className="card-head">
          <h2>Manual Expense Entry</h2>
        </div>
        <p className="subtle">Add an expense directly without uploading a statement.</p>
        <div className="filters">
          <label>
            Date
            <input type="date" value={manualDate} onChange={(e) => setManualDate(e.target.value)} />
          </label>
          <label>
            Description
            <input
              type="text"
              value={manualDescription}
              onChange={(e) => setManualDescription(e.target.value)}
              placeholder="ex: Trader Joe's"
            />
          </label>
          <label>
            Merchant (optional)
            <input
              type="text"
              value={manualMerchant}
              onChange={(e) => setManualMerchant(e.target.value)}
              placeholder="ex: Trader Joe's #123"
            />
          </label>
          <label>
            Amount (USD)
            <input
              type="text"
              value={manualAmount}
              onChange={(e) => setManualAmount(e.target.value)}
              placeholder="ex: 42.50"
            />
          </label>
          <label>
            Category
            <select value={manualCategory} onChange={(e) => setManualCategory(e.target.value)}>
              {assignableCategories.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
              <option value={NEW_CATEGORY_OPTION}>Create new...</option>
            </select>
          </label>
          <label>
            New Category
            <input
              type="text"
              value={manualNewCategory}
              onChange={(e) => setManualNewCategory(e.target.value)}
              placeholder="only used if Create new selected"
              disabled={manualCategory !== NEW_CATEGORY_OPTION}
            />
          </label>
        </div>
        <div className="insight-actions">
          <button type="button" onClick={handleAddManualExpense} disabled={manualSaving}>
            {manualSaving ? "Saving..." : "Add Expense"}
          </button>
        </div>
        {manualError ? <p className="error">{manualError}</p> : null}
        {manualSuccess ? <p className="saved-text">{manualSuccess}</p> : null}
      </section>
      ) : null}

      {activeTab === "rules" ? (
      <section className="card">
        <div className="card-head">
          <h2>Classification Rules</h2>
          <button type="button" onClick={refreshClassificationRules} disabled={loadingRules}>
            {loadingRules ? "Refreshing..." : "Refresh"}
          </button>
        </div>
        <p className="subtle">
          Manage auto-categorization mappings used for future CSV imports. Lower priority runs first.
        </p>
        <p className="subtle">Rules config file path: <span className="mono">backend/config/classification_rules.json</span></p>
        {ruleError ? <p className="error">{ruleError}</p> : null}
        {rulesConfigMessage ? <p className="saved-text">{rulesConfigMessage}</p> : null}

        <div className="insight-actions">
          <button type="button" onClick={handleSaveRulesToConfig} disabled={rulesConfigSyncing}>
            {rulesConfigSyncing ? "Saving..." : "Save Rules to Config"}
          </button>
          <button type="button" onClick={handleLoadRulesFromConfig} disabled={rulesConfigSyncing}>
            {rulesConfigSyncing ? "Loading..." : "Load Rules from Config"}
          </button>
        </div>

        <div className="filters">
          <label>
            Rule Type
            <select value={newRuleType} onChange={(e) => setNewRuleType(e.target.value as ClassificationRuleType)}>
              {RULE_TYPES.map((ruleType) => (
                <option key={ruleType} value={ruleType}>
                  {ruleType}
                </option>
              ))}
            </select>
          </label>
          <label>
            Pattern
            <input
              type="text"
              value={newRulePattern}
              onChange={(e) => setNewRulePattern(e.target.value)}
              placeholder="ex: walmart"
            />
          </label>
          <label>
            Category
            <input
              type="text"
              value={newRuleCategory}
              onChange={(e) => setNewRuleCategory(e.target.value)}
              placeholder="ex: groceries_other"
            />
          </label>
          <label>
            Confidence
            <input
              type="text"
              value={newRuleConfidence}
              onChange={(e) => setNewRuleConfidence(e.target.value)}
              placeholder="0.9"
            />
          </label>
          <label>
            Priority
            <input
              type="text"
              value={newRulePriority}
              onChange={(e) => setNewRulePriority(e.target.value)}
              placeholder="20"
            />
          </label>
          <label className="toggle-label">
            <span>Active</span>
            <input
              type="checkbox"
              checked={newRuleActive}
              onChange={(e) => setNewRuleActive(e.target.checked)}
            />
          </label>
        </div>

        <div className="insight-actions">
          <button type="button" onClick={handleCreateRule} disabled={creatingRule}>
            {creatingRule ? "Creating..." : "Add Rule"}
          </button>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Type</th>
                <th>Pattern</th>
                <th>Category</th>
                <th>Confidence</th>
                <th>Priority</th>
                <th>Active</th>
                <th>Save</th>
                <th>Delete</th>
              </tr>
            </thead>
            <tbody>
              {classificationRules.length === 0 ? (
                <tr>
                  <td colSpan={8} className="empty">
                    {loadingRules ? "Loading rules..." : "No rules found."}
                  </td>
                </tr>
              ) : (
                classificationRules.map((rule) => {
                  const draft = ruleDrafts[rule.id] ?? toRuleDraft(rule);
                  return (
                    <tr key={rule.id}>
                      <td>
                        <select
                          value={draft.rule_type}
                          onChange={(e) =>
                            setRuleDrafts((prev) => ({
                              ...prev,
                              [rule.id]: {
                                ...draft,
                                rule_type: e.target.value as ClassificationRuleType
                              }
                            }))
                          }
                        >
                          {RULE_TYPES.map((ruleType) => (
                            <option key={ruleType} value={ruleType}>
                              {ruleType}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <input
                          type="text"
                          value={draft.pattern}
                          onChange={(e) =>
                            setRuleDrafts((prev) => ({
                              ...prev,
                              [rule.id]: {
                                ...draft,
                                pattern: e.target.value
                              }
                            }))
                          }
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          value={draft.category}
                          onChange={(e) =>
                            setRuleDrafts((prev) => ({
                              ...prev,
                              [rule.id]: {
                                ...draft,
                                category: e.target.value
                              }
                            }))
                          }
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          value={draft.confidence}
                          onChange={(e) =>
                            setRuleDrafts((prev) => ({
                              ...prev,
                              [rule.id]: {
                                ...draft,
                                confidence: e.target.value
                              }
                            }))
                          }
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          value={draft.priority}
                          onChange={(e) =>
                            setRuleDrafts((prev) => ({
                              ...prev,
                              [rule.id]: {
                                ...draft,
                                priority: e.target.value
                              }
                            }))
                          }
                        />
                      </td>
                      <td>
                        <input
                          type="checkbox"
                          checked={draft.is_active}
                          onChange={(e) =>
                            setRuleDrafts((prev) => ({
                              ...prev,
                              [rule.id]: {
                                ...draft,
                                is_active: e.target.checked
                              }
                            }))
                          }
                        />
                      </td>
                      <td>
                        <button
                          type="button"
                          onClick={() => handleSaveRule(rule.id)}
                          disabled={ruleSaveState[rule.id] === "saving"}
                        >
                          {ruleSaveState[rule.id] === "saving" ? "Saving..." : "Save"}
                        </button>
                        {ruleSaveState[rule.id] === "saved" ? <span className="saved">saved</span> : null}
                        {ruleSaveState[rule.id] === "error" ? <span className="error-inline">error</span> : null}
                      </td>
                      <td>
                        <button
                          type="button"
                          onClick={() => handleDeleteRule(rule.id)}
                          disabled={deletingRuleId === rule.id}
                        >
                          {deletingRuleId === rule.id ? "Deleting..." : "Delete"}
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </section>
      ) : null}

      {activeTab === "transactions" ? (
      <section className="card">
        <div className="card-head">
          <h2>Transaction Review</h2>
          <div className="card-head-actions">
            <button type="button" onClick={handleRecategorizeTransactions} disabled={recategorizing}>
              {recategorizing ? "Re-categorizing..." : "Re-categorize"}
            </button>
            <button type="button" onClick={refreshTransactions} disabled={loadingTransactions}>
              {loadingTransactions ? "Refreshing..." : "Refresh"}
            </button>
            <button
              type="button"
              onClick={() => setTransactionReviewExpanded((prev) => !prev)}
            >
              {transactionReviewExpanded ? "Collapse" : "Expand"}
            </button>
          </div>
        </div>
        <p className="subtle">
          {loadingTransactions ? "Loading transactions..." : `${transactions.length} transactions (current filters)`}
        </p>

        {transactionReviewExpanded ? (
        <>
        <div className="filters">
          <label>
            Start
            <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </label>
          <label>
            End
            <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </label>
          <label>
            Category
            <select value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="">All categories</option>
              {categories.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
        </div>

        {txError ? <p className="error">{txError}</p> : null}
        {recategorizeMessage ? <p className="saved-text">{recategorizeMessage}</p> : null}

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Merchant</th>
                <th>Description</th>
                <th>Amount</th>
                <th>Category</th>
                <th>Save</th>
              </tr>
            </thead>
            <tbody>
              {transactions.length === 0 ? (
                <tr>
                  <td colSpan={6} className="empty">
                    {loadingTransactions ? "Loading transactions..." : "No transactions found."}
                  </td>
                </tr>
              ) : (
                transactions.map((tx) => (
                  <tr key={tx.id}>
                    <td>{tx.transaction_date ?? "n/a"}</td>
                    <td>{tx.merchant_normalized}</td>
                    <td title={tx.description_raw}>{tx.description_raw}</td>
                    <td className={tx.direction === "debit" ? "amount-debit" : "amount-credit"}>
                      {tx.direction === "debit" ? "-" : "+"}${tx.amount.toFixed(2)}
                    </td>
                    <td>
                      <select
                        value={editDrafts[tx.id] ?? tx.category}
                        onChange={(e) =>
                          setEditDrafts((prev) => ({
                            ...prev,
                            [tx.id]: e.target.value
                          }))
                        }
                      >
                        {categories.map((item) => (
                          <option key={item} value={item}>
                            {item}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <button
                        type="button"
                        onClick={() => saveCategory(tx.id)}
                        disabled={saveState[tx.id] === "saving"}
                      >
                        {saveState[tx.id] === "saving" ? "Saving..." : "Save"}
                      </button>
                      {saveState[tx.id] === "saved" ? <span className="saved">saved</span> : null}
                      {saveState[tx.id] === "error" ? <span className="error-inline">error</span> : null}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        </>
        ) : null}
      </section>
      ) : null}

      {activeTab === "transactions" ? (
      <section className="card">
        <div className="card-head">
          <h2>Uncategorized Review</h2>
          <div className="card-head-actions">
            <button type="button" onClick={refreshUncategorized} disabled={loadingUncategorized}>
              {loadingUncategorized ? "Refreshing..." : "Refresh"}
            </button>
            <button
              type="button"
              onClick={() => setUncategorizedReviewExpanded((prev) => !prev)}
            >
              {uncategorizedReviewExpanded ? "Collapse" : "Expand"}
            </button>
          </div>
        </div>
        <p className="subtle">
          {loadingUncategorized ? "Loading uncategorized..." : `${uncategorizedRows.length} uncategorized transactions`}
        </p>
        {uncategorizedReviewExpanded ? (
        <>
        {loadingCategories ? <p className="subtle">Loading categories...</p> : null}
        {categoryError ? <p className="error">{categoryError}</p> : null}
        {uncategorizedError ? <p className="error">{uncategorizedError}</p> : null}

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Merchant</th>
                <th>Description</th>
                <th>Amount</th>
                <th>Assign</th>
                <th>New Category</th>
                <th>Apply</th>
              </tr>
            </thead>
            <tbody>
              {uncategorizedRows.length === 0 ? (
                <tr>
                  <td colSpan={7} className="empty">
                    {loadingUncategorized ? "Loading uncategorized..." : "No uncategorized transactions."}
                  </td>
                </tr>
              ) : (
                uncategorizedRows.map((tx) => {
                  const selection = uncategorizedSelection[tx.id] ?? assignableCategories[0] ?? NEW_CATEGORY_OPTION;
                  return (
                    <tr key={tx.id}>
                      <td>{tx.transaction_date ?? "n/a"}</td>
                      <td>{tx.merchant_normalized}</td>
                      <td title={tx.description_raw}>{tx.description_raw}</td>
                      <td className={tx.direction === "debit" ? "amount-debit" : "amount-credit"}>
                        {tx.direction === "debit" ? "-" : "+"}${tx.amount.toFixed(2)}
                      </td>
                      <td>
                        <select
                          value={selection}
                          onChange={(e) =>
                            setUncategorizedSelection((prev) => ({
                              ...prev,
                              [tx.id]: e.target.value
                            }))
                          }
                        >
                          {assignableCategories.map((item) => (
                            <option key={item} value={item}>
                              {item}
                            </option>
                          ))}
                          <option value={NEW_CATEGORY_OPTION}>Create new...</option>
                        </select>
                      </td>
                      <td>
                        <input
                          type="text"
                          placeholder="new category"
                          value={newCategoryInputs[tx.id] ?? ""}
                          onChange={(e) =>
                            setNewCategoryInputs((prev) => ({
                              ...prev,
                              [tx.id]: e.target.value
                            }))
                          }
                          disabled={selection !== NEW_CATEGORY_OPTION}
                        />
                      </td>
                      <td>
                        <button
                          type="button"
                          onClick={() => applyUncategorizedCategory(tx.id)}
                          disabled={uncategorizedSaveState[tx.id] === "saving"}
                        >
                          {uncategorizedSaveState[tx.id] === "saving" ? "Applying..." : "Apply"}
                        </button>
                        {uncategorizedSaveState[tx.id] === "saved" ? <span className="saved">saved</span> : null}
                        {uncategorizedSaveState[tx.id] === "error" ? <span className="error-inline">error</span> : null}
                        {uncategorizedRowError[tx.id] ? <p className="error-row">{uncategorizedRowError[tx.id]}</p> : null}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
        </>
        ) : null}
      </section>
      ) : null}

      {activeTab === "transactions" ? (
      <section className="card">
        <div className="card-head">
          <h2>Duplicate Review Queue</h2>
          <div className="card-head-actions">
            <button type="button" onClick={refreshDuplicateReviews} disabled={loadingDuplicateReviews}>
              {loadingDuplicateReviews ? "Refreshing..." : "Refresh"}
            </button>
            <button
              type="button"
              onClick={() => setDuplicateReviewExpanded((prev) => !prev)}
            >
              {duplicateReviewExpanded ? "Collapse" : "Expand"}
            </button>
          </div>
        </div>
        <p className="subtle">
          {loadingDuplicateReviews ? "Loading duplicate queue..." : `${duplicateReviews.length} pending duplicate reviews`}
        </p>
        {duplicateReviewExpanded ? (
        <>
        <p className="subtle">
          Potential duplicates are queued here instead of being silently dropped during import.
        </p>
        {duplicateReviewError ? <p className="error">{duplicateReviewError}</p> : null}
        {duplicateReviewMessage ? <p className="saved-text">{duplicateReviewMessage}</p> : null}
        <div className="insight-actions">
          <button
            type="button"
            onClick={() => handleBulkResolveDuplicateReviews("mark_duplicate")}
            disabled={duplicateBulkResolvingAction !== null || duplicateReviews.length === 0}
          >
            {duplicateBulkResolvingAction === "mark_duplicate" ? "Processing..." : "Mark all shown duplicate"}
          </button>
          <button
            type="button"
            onClick={() => handleBulkResolveDuplicateReviews("not_duplicate")}
            disabled={duplicateBulkResolvingAction !== null || duplicateReviews.length === 0}
          >
            {duplicateBulkResolvingAction === "not_duplicate" ? "Processing..." : "Approve all shown"}
          </button>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Import</th>
                <th>Row</th>
                <th>Date</th>
                <th>Merchant</th>
                <th>Amount</th>
                <th>Reason</th>
                <th>Matched Txn</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {duplicateReviews.length === 0 ? (
                <tr>
                  <td colSpan={8} className="empty">
                    {loadingDuplicateReviews ? "Loading duplicate queue..." : "No pending duplicate reviews."}
                  </td>
                </tr>
              ) : (
                duplicateReviews.map((row) => (
                  <tr key={row.id}>
                    <td className="mono">{row.source_import_id}</td>
                    <td>{row.source_row_number}</td>
                    <td>{row.transaction_date ?? "n/a"}</td>
                    <td title={row.description_raw}>{row.merchant_normalized}</td>
                    <td className={row.direction === "debit" ? "amount-debit" : "amount-credit"}>
                      {row.direction === "debit" ? "-" : "+"}${row.amount.toFixed(2)}
                    </td>
                    <td>{row.duplicate_scope}:{row.duplicate_reason}</td>
                    <td className="mono">{row.matched_transaction_id ?? "n/a"}</td>
                    <td>
                      <div className="card-head-actions">
                        <button
                          type="button"
                          onClick={() => handleResolveDuplicateReview(row.id, "mark_duplicate")}
                          disabled={duplicateReviewActionState[row.id] === "saving" || duplicateBulkResolvingAction !== null}
                        >
                          Mark Duplicate
                        </button>
                        <button
                          type="button"
                          onClick={() => handleResolveDuplicateReview(row.id, "not_duplicate")}
                          disabled={duplicateReviewActionState[row.id] === "saving" || duplicateBulkResolvingAction !== null}
                        >
                          Not Duplicate
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        </>
        ) : null}
      </section>
      ) : null}

      {activeTab === "insights" ? (
      <section className="card">
        <div className="card-head">
          <h2>Insights</h2>
        </div>
        <p className="subtle">Generate a spend insight report for all data or a custom date range.</p>

        <div className="filters filters-insights">
          <label>
            Start
            <input type="date" value={insightStartDate} onChange={(e) => setInsightStartDate(e.target.value)} />
          </label>
          <label>
            End
            <input type="date" value={insightEndDate} onChange={(e) => setInsightEndDate(e.target.value)} />
          </label>
          <label>
            Existing Insight Id
            <input
              type="text"
              value={insightId}
              onChange={(e) => setInsightId(e.target.value)}
              placeholder="paste insight id"
            />
          </label>
        </div>

        <div className="insight-actions">
          <button type="button" onClick={handleGenerateInsights} disabled={generatingInsight}>
            {generatingInsight ? "Generating..." : "Generate Insights"}
          </button>
          <button type="button" onClick={handleLoadInsight} disabled={loadingInsight}>
            {loadingInsight ? "Loading..." : "Load by Id"}
          </button>
        </div>

        {insightError ? <p className="error">{insightError}</p> : null}

        {insightReport ? (
          <div className="insight-panel">
            <div className="insight-meta">
              <p>
                <strong>Report Id:</strong> <span className="mono">{insightReport.id}</span>
              </p>
              <p>
                <strong>Date Range:</strong>{" "}
                {insightReport.start_date || "all"} to {insightReport.end_date || "all"}
              </p>
              <p>
                <strong>Confidence:</strong> {(insightReport.payload.confidence * 100).toFixed(0)}%
              </p>
            </div>

            <div className="insight-summary">
              <h3>Summary</h3>
              <p>{insightReport.summary}</p>
            </div>

            <div className="insight-grid">
              <div className="insight-block">
                <h3>Top Spend Drivers</h3>
                {insightReport.payload.top_spend_drivers.length === 0 ? (
                  <p className="subtle">No data.</p>
                ) : (
                  <ul>
                    {insightReport.payload.top_spend_drivers.map((item) => (
                      <li key={`${item.category}-${item.amount}`}>
                        <span>{item.category}</span>
                        <strong>${item.amount.toFixed(2)}</strong>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <div className="insight-block">
                <h3>Top Merchants</h3>
                {insightReport.payload.top_merchants.length === 0 ? (
                  <p className="subtle">No data.</p>
                ) : (
                  <ul>
                    {insightReport.payload.top_merchants.map((item) => (
                      <li key={`${item.merchant}-${item.amount}`}>
                        <span>{item.merchant}</span>
                        <strong>${item.amount.toFixed(2)}</strong>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>

            <div className="insight-block">
              <h3>Potential Savings Actions</h3>
              {insightReport.payload.potential_savings_actions.length === 0 ? (
                <p className="subtle">No actions suggested.</p>
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Category</th>
                        <th>Current Spend</th>
                        <th>Suggested Cut</th>
                        <th>Potential Savings</th>
                        <th>Reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {insightReport.payload.potential_savings_actions.map((item) => (
                        <tr key={`${item.category}-${item.current_spend}`}>
                          <td>{item.category}</td>
                          <td>${item.current_spend.toFixed(2)}</td>
                          <td>{item.suggested_reduction_pct}%</td>
                          <td>${item.suggested_monthly_savings.toFixed(2)}</td>
                          <td>{item.reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        ) : null}
      </section>
      ) : null}
    </main>
    </SignedIn>
    </>
  );
}
