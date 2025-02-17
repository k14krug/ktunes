document.getElementById("bulk-get-genres").addEventListener("click", async () => {
    const params = new URLSearchParams(window.location.search);

    try {
        const response = await fetch("/genres/suggest", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ filters: Object.fromEntries(params.entries()) }),
        });

        console.log("Response status:", response.status); // Debug the response status
        const data = await response.json();
        console.log("Response data:", data); // Debug the returned JSON

        if (data.error) {
            alert("Error fetching recommendations: " + data.error);
        } else {
            alert("Recommendations received: " + JSON.stringify(data.suggestions));
        }
    } catch (error) {
        console.error("Fetch error:", error); // Log any fetch-related errors
        alert("An error occurred while fetching genre recommendations.");
    }
});

document.getElementById("bulk-assign-genres").addEventListener("click", async () => {
    // Collect genres to assign (could use a modal or input field for this)
    const genres = prompt("Enter genres to assign (comma-separated):").split(",");

    // Get filters from the current URL
    const params = new URLSearchParams(window.location.search);

    try {
        const response = await fetch("/genres/assign", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ filters: Object.fromEntries(params.entries()), genres }),
        });

        if (response.ok) {
            alert("Genres assigned successfully!");
        } else {
            alert("Error assigning genres.");
        }
    } catch (error) {
        alert("An error occurred while assigning genres.");
    }
});

document.getElementById("bulk-remove-genres").addEventListener("click", async () => {
    // Collect genres to remove (could use a modal or input field for this)
    const genres = prompt("Enter genres to remove (comma-separated):").split(",");

    // Get filters from the current URL
    const params = new URLSearchParams(window.location.search);

    try {
        const response = await fetch("/genres/remove", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ filters: Object.fromEntries(params.entries()), genres }),
        });

        if (response.ok) {
            alert("Genres removed successfully!");
        } else {
            alert("Error removing genres.");
        }
    } catch (error) {
        alert("An error occurred while removing genres.");
    }
});
