//  Lenticularis___Process_InsightsUITestsLaunchTests.swift
//  Lenticularis – Process Insights
//
//  Captures a launch screenshot of the native macOS app so the launch state is
//  visible in the test report.

import XCTest

final class Lenticularis___Process_InsightsUITestsLaunchTests: XCTestCase {

    private static let appBundleID = "com.beerbohm.dirk.lenticularis---Process-Insights"

    override class var runsForEachTargetApplicationUIConfiguration: Bool {
        true
    }

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    @MainActor
    func testLaunch() throws {
        let app = XCUIApplication(bundleIdentifier: Self.appBundleID)
        app.launch()

        // Add navigation/sign-in steps here before the screenshot if needed.
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = "Launch Screen"
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
