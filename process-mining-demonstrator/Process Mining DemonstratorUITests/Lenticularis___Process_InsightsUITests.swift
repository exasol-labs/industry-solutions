//  Lenticularis___Process_InsightsUITests.swift
//  Lenticularis – Process Insights
//
//  UI tests for the native macOS app. The app is launched explicitly by its
//  bundle identifier so the tests do not depend on the host-target build
//  setting, and no live database connection is required to reach the main UI.

import XCTest

final class Lenticularis___Process_InsightsUITests: XCTestCase {

    /// Bundle identifier of the macOS app under test.
    private static let appBundleID = "com.beerbohm.dirk.lenticularis---Process-Insights"

    private func launchedApp() -> XCUIApplication {
        let app = XCUIApplication(bundleIdentifier: Self.appBundleID)
        app.launch()
        return app
    }

    override func setUpWithError() throws {
        // Stop at the first failure so a broken launch doesn't cascade.
        continueAfterFailure = false
    }

    @MainActor
    func testAppLaunchesIntoForeground() throws {
        let app = launchedApp()
        XCTAssertEqual(app.state, .runningForeground,
                       "The app should be running in the foreground after launch.")
    }

    @MainActor
    func testMainWindowAppears() throws {
        let app = launchedApp()
        XCTAssertTrue(app.windows.firstMatch.waitForExistence(timeout: 10),
                      "The app should present a main window shortly after launch.")
    }

    @MainActor
    func testLaunchPerformance() throws {
        measure(metrics: [XCTApplicationLaunchMetric()]) {
            XCUIApplication(bundleIdentifier: Self.appBundleID).launch()
        }
    }
}
