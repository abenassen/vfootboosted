const data = {
  stats: [
    {
      label: 'Goals',
      row: [
        {
          label: '2021',
          value: 48,
        },
        {
          label: '2022',
          value: 35,
        },
        {
          label: 'Career',
          value: 122,
        },
      ],
    },
    {
      label: 'Assists',
      row: [
        {
          label: '2021',
          value: 27,
        },
        {
          label: '2022',
          value: 12,
        },
        {
          label: 'Career',
          value: 46,
        },
      ],
    },
    {
      label: 'Fouls',
      row: [
        {
          label: '2021',
          value: 31,
        },
        {
          label: '2022',
          value: 12,
        },
        {
          label: 'Career',
          value: 77,
        },
      ],
    },
    {
      label: 'Yellow Cards',
      row: [
        {
          label: '2021',
          value: 9,
        },
        {
          label: '2022',
          value: 3,
        },
        {
          label: 'Career',
          value: 14,
        },
      ],
    },
    {
      label: 'Red Cards',
      row: [
        {
          label: '2021',
          value: 4,
        },
        {
          label: '2022',
          value: 0,
        },
        {
          label: 'Career',
          value: 8,
        },
      ],
    },
  ],
  performance: [
    {
      label: 'Shots Accuracy',
      value: 81,
    },
    {
      label: 'Passes Accuracy',
      value: 67,
    },
  ],
};

export default function FeaturedPlayer3() {
  return (
    <div className="mx-auto w-[500px] px-5">
      <div className="@container rounded-3xl border border-custom-gray-200 bg-white dark:border-custom-gray-600 dark:bg-custom-gray-800">
        <div className="px-6 py-6 @md:px-8 @md:py-7">
          <h3 className="text-base/tight font-bold text-custom-gray-900 dark:text-white">Featured Player V3</h3>
        </div>

        <div className="relative isolate h-[222px] overflow-hidden rounded-t-3xl bg-team-golden-primary ring-1 ring-custom-gray-200 dark:ring-custom-gray-600">
          <div className="absolute start-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 text-center text-[120px]/[0.8em] font-extrabold tracking-[-0.07em] text-white uppercase italic opacity-40 mix-blend-overlay">
            <div>Logan</div>
            <div>LeBeau</div>
          </div>
          <img
            src="https://danfisher-bucket-1.s3.us-east-2.amazonaws.com/sportyblocks/player-3.png"
            alt="Player"
            className="absolute start-1/2 -top-2 max-w-[320px] -translate-x-1/2 @md:-top-4"
          />
        </div>

        <div className="relative -mt-5 overflow-hidden rounded-3xl bg-white ring-1 ring-custom-gray-200 dark:bg-custom-gray-800 dark:ring-custom-gray-600">
          <div className="flex flex-col items-center gap-2 px-20 pt-4 pb-5">
            <h2 className="text-xl/tight font-bold">Logan LeBeau</h2>
            <div className="flex flex-wrap items-center justify-center gap-2">
              <div className="inline-flex rounded-full bg-custom-yellow-300 px-3 py-1 text-[0.625rem]/none font-extrabold tracking-[0.2em] text-custom-gray-900 uppercase">
                Forward
              </div>
              <div className="inline-flex rounded-full bg-custom-gray-900 px-3 py-1 text-[0.625rem]/none font-extrabold tracking-[0.2em] text-white uppercase dark:bg-white dark:text-custom-gray-900">
                22 Years
              </div>
            </div>
            <div className="absolute start-0 top-0 flex aspect-square w-14 items-center justify-center rounded-ss-3xl rounded-ee-3xl text-xl/tight font-extrabold text-custom-gray-900 ring-1 ring-custom-gray-200 dark:text-white dark:ring-custom-gray-600">
              37
            </div>
            <div className="absolute end-0 top-0 flex aspect-square w-14 items-center justify-center rounded-se-3xl rounded-es-3xl text-xl/tight font-extrabold text-custom-gray-900 ring-1 ring-custom-gray-200 dark:ring-custom-gray-600">
              <svg viewBox="0 0 420 420" fill="none" xmlns="http://www.w3.org/2000/svg" className="h-8 w-8 text-team-golden-primary">
                <path
                  d="M201.646 416.137C144.946 389.951 97.469 343.545 60.543 278.221C30.33 224.771 13.58 169.737 4.849 132.979L0 112.558L20.478 108.517C29.676 106.701 36.353 98.519 36.353 89.064C36.353 87.535 36.171 85.986 35.811 84.46L31.579 64.862L68.813 56.045V18.129L83.947 14.518C125.355 4.884 167.706 0 210.202 0C252.699 0 294.762 4.884 336.17 14.518L351.208 18.129V56.045L388.444 64.862L384.015 84.461C383.657 85.986 383.572 87.538 383.572 89.064C383.572 98.519 390.297 106.701 399.497 108.517L420 112.558L415.161 132.981C406.428 169.739 389.684 224.774 359.473 278.221C322.549 343.545 275.075 389.95 218.367 416.141L210.01 420L201.646 416.137Z"
                  fill="currentColor"
                />
                <path
                  d="M210 26C249.08 26 288.199 30.49 326.273 39.344L330.666 40.365V44.899V76.042L357.217 82.392L362.729 83.71L361.421 89.253C360.846 91.694 360.555 94.187 360.555 96.66C360.555 111.915 371.342 125.116 386.206 128.049L392 129.194L390.628 134.969C382.592 168.782 367.193 219.379 339.47 268.405C306.042 327.514 263.28 369.405 212.366 392.909L210.001 394L207.635 392.908C156.723 369.404 113.959 327.513 80.531 268.404C52.807 219.379 37.408 168.782 29.373 134.968L28 129.193L33.795 128.048C48.658 125.115 59.446 111.914 59.446 96.659C59.446 94.185 59.154 91.692 58.579 89.252L57.272 83.709L62.784 82.391L89.335 76.041V44.898V40.365L93.727 39.344C131.802 30.49 170.921 26 210 26Z"
                  className="fill-custom-gray-900"
                />
                <path
                  d="M210 34C247.854 34 285.747 38.279 322.666 46.722V76.042V82.355L328.806 83.823L353.174 89.651C352.763 91.972 352.555 94.321 352.555 96.661C352.555 114.914 364.931 130.818 382.308 135.36C374.25 168.639 359.165 217.325 332.506 264.466C300.136 321.705 258.926 362.315 210.001 385.186C161.075 362.314 119.865 321.706 87.496 264.466C60.837 217.324 45.752 168.638 37.695 135.359C55.073 130.817 67.447 114.914 67.447 96.66C67.447 94.322 67.239 91.973 66.827 89.65L91.196 83.822L97.335 82.354V76.041V46.721C134.252 38.28 172.149 34 210 34ZM210 26C170.921 26 131.801 30.49 93.728 39.344L89.336 40.365V44.898V76.042L62.785 82.392L57.273 83.71L58.58 89.253C59.155 91.693 59.447 94.187 59.447 96.66C59.447 111.915 48.659 125.116 33.796 128.049L28 129.193L29.374 134.968C37.409 168.781 52.808 219.378 80.532 268.404C113.96 327.513 156.723 369.404 207.636 392.908L210.002 394L212.367 392.908C263.28 369.404 306.043 327.513 339.471 268.404C367.195 219.379 382.593 168.782 390.629 134.968L392.001 129.193L386.207 128.048C371.343 125.115 360.556 111.914 360.556 96.659C360.556 94.185 360.847 91.693 361.422 89.252L362.73 83.709L357.218 82.391L330.667 76.041V44.899V40.365L326.274 39.344C288.199 30.49 249.08 26 210 26Z"
                  className="fill-white"
                />
                <path
                  fillRule="evenodd"
                  clipRule="evenodd"
                  d="M210.044 114C210.044 114 254.447 142.648 304.491 145.051C304.491 145.051 309.988 171.923 307.221 198.278C307.221 198.278 290.07 198.51 271.19 193.843C271.19 193.843 272.964 183.446 272.282 177.209C272.282 177.209 233.793 170.418 210.044 156.694C210.044 156.694 176.743 171.387 148.354 177.209C148.354 177.209 147.671 197.724 152.175 213.249C152.175 213.249 187.661 208.121 210.044 197.17C210.044 197.17 251.399 215.883 305.038 217.131C305.038 217.131 282.199 303.81 210.044 338.001C210.044 338.001 163.094 319.519 135.797 272.021C135.797 272.021 156.36 271.283 175.732 266.654C176.721 268.349 192.58 281.955 210.044 293.092C210.044 293.092 238.889 281.727 255.903 247.625C255.903 247.625 227.878 244.113 210.044 236.537C210.044 236.537 169.281 250.767 127.061 252.617C127.061 252.617 103.859 207.151 115.051 144.498C115.051 144.498 168.007 144.497 210.044 114Z"
                  fill="currentColor"
                />
                <path
                  d="M218.323 65.462L210.24 49L202.157 65.462L184.081 68.102L197.16 80.916L194.073 99.009L210.24 90.467L226.406 99.009L223.319 80.916L236.398 68.102L218.323 65.462ZM148.835 90.709L142.5 77.807L136.165 90.709L122 92.777L132.25 102.819L129.831 117L142.5 110.305L155.17 117L152.75 102.82L163 92.777L148.835 90.709ZM298 92.777L283.835 90.709L277.5 77.807L271.165 90.709L256.999 92.777L267.25 102.819L264.83 117L277.5 110.305L290.17 117L287.75 102.82L298 92.777Z"
                  className="fill-white"
                />
              </svg>
            </div>
          </div>

          <div className="inline-block min-w-full align-middle">
            <table className="min-w-full table-auto border-collapse border-spacing-px rounded-t-3xl bg-custom-gray-100 ring-1 ring-custom-gray-200 dark:bg-custom-gray-700 dark:ring-custom-gray-600">
              <thead className="text-xs/tight font-bold text-custom-gray-900 uppercase dark:text-white">
                <tr>
                  <th scope="col" className="w-48 py-3.5 ps-8 pe-4 text-start">
                    Stat
                  </th>
                  <th scope="col" className="px-2.5 py-3.5 text-end">
                    2021
                  </th>
                  <th scope="col" className="px-2.5 py-3.5 text-end">
                    2022
                  </th>
                  <th scope="col" className="py-3.5 ps-1 pe-8 text-end">
                    Career
                  </th>
                </tr>
              </thead>
              <tbody className="rounded-3xl text-sm/tight font-bold text-custom-gray-900 dark:text-white [&_td]:bg-white dark:[&_td]:bg-custom-gray-800">
                {data.stats.map((stat) => (
                  <tr
                    key={stat.label}
                    className="border-b border-custom-gray-200 first:rounded-t-3xl first:ring-1 first:ring-custom-gray-200 last:border-0 dark:border-custom-gray-600 dark:ring-custom-gray-600 [&:first-child>td:first-child]:rounded-ss-3xl [&:first-child>td:last-child]:rounded-se-3xl"
                  >
                    <td className="py-5 ps-8 pe-2.5">{stat.label}</td>
                    {stat.row.map((item) => (
                      <td key={item.label} className="w-16 px-2.5 py-5 text-end last:pe-8">
                        {item.value}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex flex-col gap-y-8 p-7">
            {data.performance.map((item) => (
              <div key={item.label} className="flex flex-col gap-y-4">
                <div className="flex justify-between text-sm/tight font-bold">
                  <div>{item.label}</div>
                  <div>{item.value + '%'}</div>
                </div>
                <div className="flex h-1 overflow-hidden rounded-full bg-custom-gray-200 dark:bg-custom-gray-600">
                  <div className="h-full rounded-full bg-team-golden-primary" style={{ width: item.value + '%' }}></div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
