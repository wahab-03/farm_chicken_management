/** @odoo-module **/

import { registry } from "@web/core/registry";
import { loadJS } from "@web/core/assets";
import { useBus, useService } from "@web/core/utils/hooks";
import { Component, useState, useRef, onWillStart, onMounted, onWillUnmount } from "@odoo/owl";

const MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
];

const CHICKEN_TYPE_LABELS = { deshi: "Deshi", farmer_poultry: "Farmer / Poultry", pahari: "Pahari" };
const CHICKEN_CATEGORY_LABELS = { morog: "Morog", murgi: "Murgi", baby_chicks: "Baby Chicks" };
const FEED_STAGE_LABELS = {
    baby: "Baby (0-1 Month)",
    grower: "Grower (1-2 Month)",
    grower_layer: "Grower/Layer (2-4 Month)",
    adult_layer: "Adult/Layer (4+ Month)",
};

const HATCHING_MUTATION_MODELS = new Set([
    "incubator.hatching.batch",
    "incubator.failed.egg",
]);

const HATCHING_MUTATION_METHODS = new Set([
    "create",
    "write",
    "unlink",
    "web_save",
    "action_mark_hatched",
]);

function pad2(n) {
    return String(n).padStart(2, "0");
}

function fmtNum(n) {
    if (n === null || n === undefined || isNaN(n)) return "0";
    return Math.round(n * 100) / 100 === Math.round(n)
        ? Math.round(n).toLocaleString("en-US")
        : (Math.round(n * 100) / 100).toLocaleString("en-US");
}

function fmtMoney(n) {
    return "৳" + fmtNum(n);
}

function timeAgo(dateStr) {
    if (!dateStr) return "";
    const then = new Date(dateStr.replace(" ", "T") + "Z");
    const diffMs = Date.now() - then.getTime();
    const mins = Math.floor(diffMs / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return mins + " min" + (mins > 1 ? "s" : "") + " ago";
    const hours = Math.floor(mins / 60);
    if (hours < 24) return hours + " hour" + (hours > 1 ? "s" : "") + " ago";
    const days = Math.floor(hours / 24);
    return days + " day" + (days > 1 ? "s" : "") + " ago";
}

export class ChickenFarmDashboard extends Component {
    static template = "farm_chicken_management.Dashboard";

    setup() {
        this.orm = useService("orm");
        this.charts = {};
        this.canvasRefs = {
            monthly: useRef("canvasMonthly"),
            profit: useRef("canvasProfit"),
            stockType: useRef("canvasStockType"),
            stockCategory: useRef("canvasStockCategory"),
            vaccination: useRef("canvasVaccination"),
            mortalityReason: useRef("canvasMortalityReason"),
            feedStage: useRef("canvasFeedStage"),
            hatching: useRef("canvasHatching"),
        };

        const now = new Date();
        this.state = useState({
            loading: true,
            error: null,
            now,
            years: [now.getFullYear() - 2, now.getFullYear() - 1, now.getFullYear()].reverse(),
            batches: [],
            filters: {
                year: now.getFullYear(),
                month: now.getMonth() + 1,
                chickenType: "all",
                chickenCategory: "all",
                batchId: "all",
            },
            kpi: {
                totalBatches: 0, totalBatchesDelta: 0,
                currentChickens: 0, currentChickensDelta: 0,
                mortality: 0, mortalityDelta: 0,
                eggProduction: 0, eggProductionDelta: 0,
                feedConsumed: 0, feedConsumedDelta: 0,
                salesRevenue: 0, salesRevenueDelta: 0,
                farmExpenses: 0, farmExpensesDelta: 0,
                babyChicks: 0, babyChicksDelta: 0,
            },
            monthly: { labels: [], egg: [], mortality: [], sales: [] },
            profitMargin: 0,
            profitFiltered: false,
            revenueTotal: 0,
            expenseTotal: 0,
            netProfit: 0,
            stockByType: { labels: [], data: [] },
            stockByCategory: { labels: [], data: [] },
            vaccinationStatus: { completed: 0, dueSoon: 0, overdue: 0, completedPct: 0 },
            mortalityByReason: { labels: [], data: [] },
            feedInventory: { purchased: 0, prepared: 0, rawIngredients: 0, vaccines: 0 },
            feedByStage: { labels: [], data: [] },
            hatching: { hatched: 0, failed: 0, damaged: 0, totalEggs: 0, hatchedPct: 0, failedPct: 0, damagedPct: 0, expectedDate: false },
            topBatches: [],
            recentActivities: [],
            quickStats: { liveChicken: 0, readyToCook: 0, reserved: 0, babyChicks: 0 },
        });

        onWillStart(async () => {
            await loadJS("/web/static/lib/Chart/Chart.js");
            this.state.batches = await this.orm.searchRead("chicken.batch", [], ["id", "name"], { order: "name asc" });
            await this.loadAll();
        });

        useBus(this.env.bus, "RPC:RESPONSE", (ev) => {
            const params = ev.detail?.data?.params;
            if (!params) return;

            if (HATCHING_MUTATION_MODELS.has(params.model) && HATCHING_MUTATION_METHODS.has(params.method)) {
                this._scheduleHatchingRefresh();
            }
        });

        onMounted(() => {
            this.renderCharts();
        });

        onWillUnmount(() => {
            this._destroyed = true;
            if (this._hatchingRefreshTimer) {
                clearTimeout(this._hatchingRefreshTimer);
                this._hatchingRefreshTimer = null;
            }
            Object.values(this.charts).forEach((c) => c && c.destroy());
        });
    }


    _monthName(m) {
        return m ? MONTH_NAMES[m - 1] : "All Months";
    }

    _dateRange(year, month) {
        if (!month) {
            return [`${year}-01-01`, `${year}-12-31`];
        }
        const lastDay = new Date(year, month, 0).getDate();
        return [`${year}-${pad2(month)}-01`, `${year}-${pad2(month)}-${pad2(lastDay)}`];
    }

    _prevPeriodRange(year, month) {
        if (!month) {
            return this._dateRange(year - 1, 0);
        }
        let py = year, pm = month - 1;
        if (pm === 0) { pm = 12; py -= 1; }
        return this._dateRange(py, pm);
    }

    _pct(cur, prev) {
        if (!prev) return cur ? 100 : 0;
        return Math.round(((cur - prev) / Math.abs(prev)) * 1000) / 10;
    }

    _batchFilterDomain() {
        const f = this.state.filters;
        const domain = [];
        if (f.chickenType !== "all") domain.push(["chicken_type", "=", f.chickenType]);
        if (f.chickenCategory !== "all") domain.push(["chicken_category", "=", f.chickenCategory]);
        if (f.batchId !== "all") domain.push(["id", "=", parseInt(f.batchId, 10)]);
        return domain;
    }

    _relatedBatchFilterDomain(prefix) {
        const f = this.state.filters;
        const domain = [];
        if (f.chickenType !== "all") domain.push([`${prefix}.chicken_type`, "=", f.chickenType]);
        if (f.chickenCategory !== "all") domain.push([`${prefix}.chicken_category`, "=", f.chickenCategory]);
        if (f.batchId !== "all") domain.push([prefix, "=", parseInt(f.batchId, 10)]);
        return domain;
    }

    async _sum(model, domain, field) {
        const recs = await this.orm.searchRead(model, domain, [field]);
        return recs.reduce((s, r) => s + (r[field] || 0), 0);
    }

    async _groupSum(model, domain, groupField, valueField, labelMap) {
        const recs = await this.orm.searchRead(model, domain, [groupField, valueField]);
        const map = {};
        for (const r of recs) {
            let key = r[groupField];
            if (Array.isArray(key)) key = key[1];
            if (key === false || key === undefined || key === null || key === "") key = "Unspecified";
            if (labelMap && labelMap[key]) key = labelMap[key];
            map[key] = (map[key] || 0) + (r[valueField] || 0);
        }
        return map;
    }

    async _chickenStockAsOf(dateStr) {
        const batchDomain = [...this._batchFilterDomain(), ["purchase_date", "<=", dateStr]];
        const purchased = await this._sum("chicken.batch", batchDomain, "initial_quantity");
        const deadDomain = [...this._relatedBatchFilterDomain("batch_id"), ["batch_id.active", "=", true], ["date", "<=", dateStr]];
        const dead = await this._sum("chicken.mortality", deadDomain, "total_dead");
        const soldDomain = [...this._relatedBatchFilterDomain("batch_id"), ["batch_id.active", "=", true], ["state", "=", "delivered"], ["sale_date", "<=", dateStr]];
        const sold = await this._sum("chicken.sale", soldDomain, "quantity");
        return purchased - dead - sold;
    }

    async _babyChickStockAsOf(dateStr) {
        const produced = await this._sum("baby.chicken.stock", [["hatching_date", "<=", dateStr]], "quantity");
        const sold = await this._sum("baby.chicken.sale", [["sale_date", "<=", dateStr], ["state", "=", "sold"]], "quantity");
        return produced - sold;
    }


    async onFilterChanged(ev) {
        const { name, value } = ev.target;
        if (name === "year" || name === "month") {
            this.state.filters[name] = parseInt(value, 10);
        } else {
            this.state.filters[name] = value;
        }
        await this.loadAll();
        this.renderCharts();
    }


    _scheduleHatchingRefresh() {
        if (this._hatchingRefreshTimer) clearTimeout(this._hatchingRefreshTimer);
        this._hatchingRefreshTimer = setTimeout(async () => {
            this._hatchingRefreshTimer = null;
            if (this._destroyed) return;
            await this.loadAll();
            if (!this._destroyed) this.renderCharts();
        }, 100);
    }

    async loadAll() {
        this.state.loading = true;
        this.state.error = null;
        try {
            await Promise.all([
                this._loadKpis(),
                this._loadMonthlyPerformance(),
                this._loadStockBreakdown(),
                this._loadVaccinationStatus(),
                this._loadMortalityByReason(),
                this._loadFeedInventory(),
                this._loadHatching(),
                this._loadTopBatches(),
                this._loadRecentActivities(),
                this._loadQuickStats(),
            ]);
        } catch (e) {
            console.error(e);
            this.state.error = "Dashboard data could not be fully loaded.";
        } finally {
            this.state.loading = false;
        }
    }

    async _loadKpis() {
        const f = this.state.filters;
        const [start, end] = this._dateRange(f.year, f.month);
        const [pStart, pEnd] = this._prevPeriodRange(f.year, f.month);
        const batchDomain = this._batchFilterDomain();

        const totalBatches = await this.orm.searchCount("chicken.batch", [
            ...batchDomain, ["purchase_date", ">=", start], ["purchase_date", "<=", end],
        ]);
        const prevTotalBatches = await this.orm.searchCount("chicken.batch", [
            ...batchDomain, ["purchase_date", ">=", pStart], ["purchase_date", "<=", pEnd],
        ]);

        const currentChickens = await this._chickenStockAsOf(end);
        const prevChickens = await this._chickenStockAsOf(pEnd);

        const mortDomain = [...this._relatedBatchFilterDomain("batch_id"), ["date", ">=", start], ["date", "<=", end]];
        const prevMortDomain = [...this._relatedBatchFilterDomain("batch_id"), ["date", ">=", pStart], ["date", "<=", pEnd]];
        const mortality = await this._sum("chicken.mortality", mortDomain, "total_dead");
        const prevMortality = await this._sum("chicken.mortality", prevMortDomain, "total_dead");

        const eggDomain = [...this._relatedBatchFilterDomain("batch_id"), ["date", ">=", start], ["date", "<=", end]];
        const prevEggDomain = [...this._relatedBatchFilterDomain("batch_id"), ["date", ">=", pStart], ["date", "<=", pEnd]];
        const eggProduction = await this._sum("egg.production", eggDomain, "quantity");
        const prevEggProduction = await this._sum("egg.production", prevEggDomain, "quantity");

        const feedDomain = [...this._relatedBatchFilterDomain("batch_id"), ["date", ">=", start], ["date", "<=", end]];
        const prevFeedDomain = [...this._relatedBatchFilterDomain("batch_id"), ["date", ">=", pStart], ["date", "<=", pEnd]];
        const feedConsumed = await this._sum("feed.consumption", feedDomain, "quantity");
        const prevFeedConsumed = await this._sum("feed.consumption", prevFeedDomain, "quantity");

        const saleDomain = [...this._relatedBatchFilterDomain("batch_id"), ["state", "=", "delivered"], ["sale_date", ">=", start], ["sale_date", "<=", end]];
        const prevSaleDomain = [...this._relatedBatchFilterDomain("batch_id"), ["state", "=", "delivered"], ["sale_date", ">=", pStart], ["sale_date", "<=", pEnd]];
        const babySaleDomain = [["sale_date", ">=", start], ["sale_date", "<=", end], ["state", "=", "sold"]];
        const prevBabySaleDomain = [["sale_date", ">=", pStart], ["sale_date", "<=", pEnd], ["state", "=", "sold"]];

        const noChickenFilter = f.chickenType === "all" && f.chickenCategory === "all" && f.batchId === "all";
        const salesRevenue =
            (await this._sum("chicken.sale", saleDomain, "selling_price")) +
            (noChickenFilter ? await this._sum("baby.chicken.sale", babySaleDomain, "selling_price") : 0);
        const prevSalesRevenue =
            (await this._sum("chicken.sale", prevSaleDomain, "selling_price")) +
            (noChickenFilter ? await this._sum("baby.chicken.sale", prevBabySaleDomain, "selling_price") : 0);

        const expDomain = [["date", ">=", start], ["date", "<=", end]];
        const prevExpDomain = [["date", ">=", pStart], ["date", "<=", pEnd]];
        const farmExpenses = await this._sum("farm.expense", expDomain, "amount");
        const prevFarmExpenses = await this._sum("farm.expense", prevExpDomain, "amount");

        const babyDomain = [["hatching_date", ">=", start], ["hatching_date", "<=", end]];
        const prevBabyDomain = [["hatching_date", ">=", pStart], ["hatching_date", "<=", pEnd]];
        const babyChicks = await this._sum("baby.chicken.stock", babyDomain, "quantity");
        const prevBabyChicks = await this._sum("baby.chicken.stock", prevBabyDomain, "quantity");

        Object.assign(this.state.kpi, {
            totalBatches, totalBatchesDelta: this._pct(totalBatches, prevTotalBatches),
            currentChickens, currentChickensDelta: this._pct(currentChickens, prevChickens),
            mortality, mortalityDelta: this._pct(mortality, prevMortality),
            eggProduction, eggProductionDelta: this._pct(eggProduction, prevEggProduction),
            feedConsumed, feedConsumedDelta: this._pct(feedConsumed, prevFeedConsumed),
            salesRevenue, salesRevenueDelta: this._pct(salesRevenue, prevSalesRevenue),
            farmExpenses, farmExpensesDelta: this._pct(farmExpenses, prevFarmExpenses),
            babyChicks, babyChicksDelta: this._pct(babyChicks, prevBabyChicks),
        });

        this.state.profitFiltered = !noChickenFilter;
        this.state.revenueTotal = salesRevenue;
        this.state.expenseTotal = farmExpenses;
        if (noChickenFilter) {
            this.state.netProfit = salesRevenue - farmExpenses;
            this.state.profitMargin = salesRevenue ? Math.round(((salesRevenue - farmExpenses) / salesRevenue) * 1000) / 10 : 0;
        } else {
            this.state.netProfit = 0;
            this.state.profitMargin = 0;
        }
    }

    async _loadMonthlyPerformance() {
        const f = this.state.filters;
        const year = f.year;
        const labels = [];
        const egg = [];
        const mortality = [];
        const sales = [];
        for (let m = 1; m <= 12; m++) {
            const [start, end] = this._dateRange(year, m);
            labels.push(MONTH_NAMES[m - 1].slice(0, 3));
            egg.push(await this._sum("egg.production", [
                ...this._relatedBatchFilterDomain("batch_id"), ["date", ">=", start], ["date", "<=", end],
            ], "quantity"));
            mortality.push(await this._sum("chicken.mortality", [
                ...this._relatedBatchFilterDomain("batch_id"), ["date", ">=", start], ["date", "<=", end],
            ], "total_dead"));
            sales.push(await this._sum("chicken.sale", [
                ...this._relatedBatchFilterDomain("batch_id"), ["state", "=", "delivered"], ["sale_date", ">=", start], ["sale_date", "<=", end],
            ], "quantity"));
        }
        this.state.monthly = { labels, egg, mortality, sales };
    }

    async _loadStockBreakdown() {
        const batchDomain = [...this._batchFilterDomain(), ["active", "=", true]];
        const byType = await this._groupSum("chicken.batch", batchDomain, "chicken_type", "current_quantity", CHICKEN_TYPE_LABELS);
        const byCategory = await this._groupSum("chicken.batch", batchDomain, "chicken_category", "current_quantity", CHICKEN_CATEGORY_LABELS);
        this.state.stockByType = { labels: Object.keys(byType), data: Object.values(byType) };
        this.state.stockByCategory = { labels: Object.keys(byCategory), data: Object.values(byCategory) };
    }

    async _loadVaccinationStatus() {
        const recs = await this.orm.searchRead("vaccine.batch.schedule", [], ["state"]);
        let completed = 0, dueSoon = 0, overdue = 0;
        for (const r of recs) {
            if (r.state === "done") completed++;
            else if (r.state === "overdue") overdue++;
            else dueSoon++;
        }
        const total = completed + dueSoon + overdue;
        this.state.vaccinationStatus = {
            completed, dueSoon, overdue,
            completedPct: total ? Math.round((completed / total) * 100) : 0,
            dueSoonPct: total ? Math.round((dueSoon / total) * 100) : 0,
            overduePct: total ? Math.round((overdue / total) * 100) : 0,
        };
    }

    async _loadMortalityByReason() {
        const f = this.state.filters;
        const [start, end] = this._dateRange(f.year, f.month);
        const domain = [...this._relatedBatchFilterDomain("batch_id"), ["date", ">=", start], ["date", "<=", end]];
        const recs = await this.orm.searchRead("chicken.mortality", domain, ["reason", "total_dead"]);
        const map = {};
        for (const r of recs) {
            const key = (r.reason || "").trim() || "Not Specified";
            map[key] = (map[key] || 0) + (r.total_dead || 0);
        }
        const entries = Object.entries(map).sort((a, b) => b[1] - a[1]);
        const top = entries.slice(0, 5);
        const restTotal = entries.slice(5).reduce((s, e) => s + e[1], 0);
        if (restTotal > 0) top.push(["Other", restTotal]);
        this.state.mortalityByReason = { labels: top.map((e) => e[0]), data: top.map((e) => e[1]) };
    }

    async _loadFeedInventory() {
        const purchasedFeed = await this.orm.searchRead("feed.product", [["source_type", "=", "purchased"]], ["current_stock"]);
        const preparedFeed = await this.orm.searchRead("feed.product", [["source_type", "=", "self_mixed"]], ["current_stock"]);
        const rawIngredients = await this.orm.searchRead("feed.ingredient", [], ["current_stock"]);
        const vaccines = await this.orm.searchRead("vaccine.vaccine", [], ["current_stock"]);

        const sumStock = (recs) => recs.reduce((s, r) => s + (r.current_stock || 0), 0);
        this.state.feedInventory = {
            purchased: sumStock(purchasedFeed),
            prepared: sumStock(preparedFeed),
            rawIngredients: sumStock(rawIngredients),
            vaccines: sumStock(vaccines),
        };

        const stageRecs = await this.orm.searchRead("feed.product", [], ["feed_category", "current_stock"]);
        const stageMap = {};
        for (const r of stageRecs) {
            const label = FEED_STAGE_LABELS[r.feed_category] || "Unspecified";
            stageMap[label] = (stageMap[label] || 0) + (r.current_stock || 0);
        }
        this.state.feedByStage = { labels: Object.keys(stageMap), data: Object.values(stageMap) };
    }

    async _loadHatching() {
        const f = this.state.filters;
        const [start, end] = this._dateRange(f.year, f.month);
        const batches = await this.orm.searchRead("incubator.hatching.batch", [
            ["start_date", ">=", start], ["start_date", "<=", end],
        ], ["id", "number_of_eggs", "hatched_chicks"]);
        const totalEggs = batches.reduce((s, b) => s + (b.number_of_eggs || 0), 0);
        const hatched = batches.reduce((s, b) => s + (b.hatched_chicks || 0), 0);
        const batchIds = batches.map((b) => b.id);
        let failed = 0, damaged = 0;
        if (batchIds.length) {
            const failedRecs = await this.orm.searchRead("incubator.failed.egg", [
                ["hatching_batch_id", "in", batchIds],
            ], ["failed_eggs", "damaged_eggs"]);
            failed = failedRecs.reduce((s, r) => s + (r.failed_eggs || 0), 0);
            damaged = failedRecs.reduce((s, r) => s + (r.damaged_eggs || 0), 0);
        }
        const nearest = await this.orm.searchRead("incubator.hatching.batch", [
            ["actual_hatching_date", "=", false],
        ], ["expected_hatching_date"], { order: "expected_hatching_date asc", limit: 1 });

        this.state.hatching = {
            totalEggs, hatched, failed, damaged,
            hatchedPct: totalEggs ? Math.round((hatched / totalEggs) * 100) : 0,
            failedPct: totalEggs ? Math.round((failed / totalEggs) * 100) : 0,
            damagedPct: totalEggs ? Math.round((damaged / totalEggs) * 100) : 0,
            expectedDate: nearest.length ? nearest[0].expected_hatching_date : false,
        };
    }

    async _loadTopBatches() {
        const domain = [...this._batchFilterDomain(), ["active", "=", true]];
        const batches = await this.orm.searchRead("chicken.batch", domain, [
            "name", "chicken_type", "current_quantity", "total_mortality", "active",
        ], { order: "current_quantity desc", limit: 6 });
        this.state.topBatches = batches.map((b) => ({
            name: b.name,
            chickenType: CHICKEN_TYPE_LABELS[b.chicken_type] || b.chicken_type,
            currentQuantity: b.current_quantity,
            mortality: b.total_mortality,
            status: b.active ? "Active" : "Closed",
        }));
    }

    async _loadRecentActivities() {
        const activities = [];
        const sales = await this.orm.searchRead("chicken.sale", this._relatedBatchFilterDomain("batch_id"), ["name", "batch_id", "create_date"], { order: "create_date desc", limit: 3 });
        for (const s of sales) {
            activities.push({ icon: "fa-shopping-cart", text: `Sale recorded (${s.name})`, date: s.create_date });
        }
        const mortalities = await this.orm.searchRead("chicken.mortality", this._relatedBatchFilterDomain("batch_id"), ["batch_id", "create_date"], { order: "create_date desc", limit: 3 });
        for (const m of mortalities) {
            activities.push({ icon: "fa-heartbeat", text: `Mortality recorded (${m.batch_id ? m.batch_id[1] : ""})`, date: m.create_date });
        }
        const eggs = await this.orm.searchRead("egg.production", this._relatedBatchFilterDomain("batch_id"), ["batch_id", "create_date"], { order: "create_date desc", limit: 3 });
        for (const e of eggs) {
            activities.push({ icon: "fa-circle-o", text: `Egg collection (${e.batch_id ? e.batch_id[1] : ""})`, date: e.create_date });
        }
        const vacc = await this.orm.searchRead("vaccine.batch.schedule", [["state", "=", "done"]], ["vaccine_id", "create_date"], { order: "create_date desc", limit: 3 });
        for (const v of vacc) {
            activities.push({ icon: "fa-medkit", text: `Vaccination completed (${v.vaccine_id ? v.vaccine_id[1] : ""})`, date: v.create_date });
        }
        const feedPurch = await this.orm.searchRead("feed.product.purchase", [], ["feed_id", "create_date"], { order: "create_date desc", limit: 2 });
        for (const fp of feedPurch) {
            activities.push({ icon: "fa-shopping-basket", text: `Feed purchase (${fp.feed_id ? fp.feed_id[1] : ""})`, date: fp.create_date });
        }

        activities.sort((a, b) => (a.date < b.date ? 1 : -1));
        this.state.recentActivities = activities.slice(0, 6).map((a) => ({ ...a, ago: timeAgo(a.date) }));
    }

    async _loadQuickStats() {
        const today = new Date().toISOString().slice(0, 10);
        const batchDomain = [...this._batchFilterDomain(), ["active", "=", true]];
        const batches = await this.orm.searchRead("chicken.batch", batchDomain, ["chicken_category", "current_quantity", "reserved_quantity"]);
        let liveChicken = 0, reserved = 0;
        for (const b of batches) {
            if (b.chicken_category !== "baby_chicks") liveChicken += b.current_quantity || 0;
            reserved += b.reserved_quantity || 0;
        }
        const readyToCook = await this._sum("chicken.sale", [
            ...this._relatedBatchFilterDomain("batch_id"), ["sale_subcategory", "=", "ready_to_cook"], ["state", "=", "delivered"],
        ], "quantity");
        const babyStock = await this.orm.searchRead("baby.chicken.stock", [["state", "=", "in_stock"]], ["current_quantity"]);
        const babyChicks = babyStock.reduce((s, r) => s + (r.current_quantity || 0), 0);

        this.state.quickStats = { liveChicken, readyToCook, reserved, babyChicks };
    }


    _destroyChart(key) {
        if (this.charts[key]) {
            this.charts[key].destroy();
            delete this.charts[key];
        }
    }

    renderCharts() {
        const Chart = window.Chart;
        if (!Chart) return;

        this._destroyChart("monthly");
        const elMonthly = this.canvasRefs.monthly.el;
        if (elMonthly) {
            this.charts.monthly = new Chart(elMonthly.getContext("2d"), {
                type: "line",
                data: {
                    labels: this.state.monthly.labels,
                    datasets: [
                        { label: "Egg Production", data: this.state.monthly.egg, borderColor: "#22c55e", backgroundColor: "rgba(34,197,94,0.15)", tension: 0.35, fill: true },
                        { label: "Mortality", data: this.state.monthly.mortality, borderColor: "#ef4444", backgroundColor: "rgba(239,68,68,0.1)", tension: 0.35, fill: false },
                        { label: "Sales (qty)", data: this.state.monthly.sales, borderColor: "#3b82f6", backgroundColor: "rgba(59,130,246,0.12)", tension: 0.35, fill: true },
                    ],
                },
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "top" } } },
            });
        }

        this._destroyChart("profit");
        const elProfit = this.canvasRefs.profit.el;
        if (elProfit) {
            const margin = Math.max(Math.min(this.state.profitMargin, 100), 0);
            this.charts.profit = new Chart(elProfit.getContext("2d"), {
                type: "doughnut",
                data: {
                    labels: ["Net Margin", "Remainder"],
                    datasets: [{ data: [margin, 100 - margin], backgroundColor: ["#16a34a", "#e5e7eb"], borderWidth: 0 }],
                },
                options: {
                    responsive: true, maintainAspectRatio: false, circumference: 180, rotation: 270, cutout: "75%",
                    plugins: { legend: { display: false }, tooltip: { enabled: false } },
                },
            });
        }

        this._destroyChart("stockType");
        const elStockType = this.canvasRefs.stockType.el;
        if (elStockType) {
            this.charts.stockType = new Chart(elStockType.getContext("2d"), {
                type: "bar",
                data: {
                    labels: this.state.stockByType.labels,
                    datasets: [{ label: "Current Qty", data: this.state.stockByType.data, backgroundColor: ["#22c55e", "#3b82f6", "#f59e0b", "#a855f7"] }],
                },
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
            });
        }

        this._destroyChart("stockCategory");
        const elStockCategory = this.canvasRefs.stockCategory.el;
        if (elStockCategory) {
            this.charts.stockCategory = new Chart(elStockCategory.getContext("2d"), {
                type: "doughnut",
                data: {
                    labels: this.state.stockByCategory.labels,
                    datasets: [{ data: this.state.stockByCategory.data, backgroundColor: ["#3b82f6", "#f59e0b", "#a855f7", "#22c55e"] }],
                },
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "right" } } },
            });
        }

        this._destroyChart("vaccination");
        const elVaccination = this.canvasRefs.vaccination.el;
        if (elVaccination) {
            const v = this.state.vaccinationStatus;
            this.charts.vaccination = new Chart(elVaccination.getContext("2d"), {
                type: "doughnut",
                data: {
                    labels: ["Completed", "Due Soon", "Overdue"],
                    datasets: [{ data: [v.completed, v.dueSoon, v.overdue], backgroundColor: ["#16a34a", "#f59e0b", "#ef4444"] }],
                },
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
            });
        }

        this._destroyChart("mortalityReason");
        const elMortReason = this.canvasRefs.mortalityReason.el;
        if (elMortReason) {
            this.charts.mortalityReason = new Chart(elMortReason.getContext("2d"), {
                type: "bar",
                data: {
                    labels: this.state.mortalityByReason.labels,
                    datasets: [{ label: "Dead", data: this.state.mortalityByReason.data, backgroundColor: "#ef4444" }],
                },
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
            });
        }

        this._destroyChart("feedStage");
        const elFeedStage = this.canvasRefs.feedStage.el;
        if (elFeedStage) {
            this.charts.feedStage = new Chart(elFeedStage.getContext("2d"), {
                type: "bar",
                data: {
                    labels: this.state.feedByStage.labels,
                    datasets: [{ label: "Stock (kg)", data: this.state.feedByStage.data, backgroundColor: "#0ea5e9" }],
                },
                options: { indexAxis: "y", responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
            });
        }

        this._destroyChart("hatching");
        const elHatching = this.canvasRefs.hatching.el;
        if (elHatching) {
            const h = this.state.hatching;
            const remaining = Math.max(h.totalEggs - h.hatched - h.failed - h.damaged, 0);
            this.charts.hatching = new Chart(elHatching.getContext("2d"), {
                type: "doughnut",
                data: {
                    labels: ["Hatched", "Failed", "Damaged", "In Progress"],
                    datasets: [{ data: [h.hatched, h.failed, h.damaged, remaining], backgroundColor: ["#16a34a", "#ef4444", "#f59e0b", "#94a3b8"] }],
                },
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
            });
        }
    }

    fmtNum(n) { return fmtNum(n); }
    fmtMoney(n) { return fmtMoney(n); }
}

registry.category("actions").add("chicken_farm_dashboard_action", ChickenFarmDashboard);
